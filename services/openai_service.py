import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import aiohttp
from aiohttp import ClientSession, ClientTimeout

# === ОНОВЛЕНІ ПРОМПТИ ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ (VISION API) ===
PROFILE_SCREENSHOT_PROMPT = """
Ти — MLBB аналітик. Витягни дані з скріншота профілю. Поверни ТІЛЬКИ JSON.
{
  "game_nickname": "string або null",
  "mlbb_id_server": "string 'ID (SERVER)' або null (приклад: '123456789 (1234)')",
  "highest_rank_season": "string (приклад: 'Міфічна Слава 267 ★') або null",
  "matches_played": "int або null (знизу скріншота)",
  "likes_received": "int або null (знизу скріншота)",
  "location": "string або null",
  "squad_name": "string або null"
}
ВАЖЛИВО:
1.  **ID/Server (mlbb_id_server):** Шукай біля іконки профілю. Формат 'ID (SERVER)'.
2.  **Матчі (Matches Played) / Лайки (Likes Received):** Знаходяться ВНИЗУ. Не плутай з очками популярності.
3.  **Найвищий Ранг (Highest Rank):** Під написом "Highest Rank". Включай зірки/очки.
4.  **Сквад (Squad Name):** Повна назва.
5.  **Відсутні дані:** Використовуй `null`.
Точність є критичною.
"""

PLAYER_STATS_PROMPT = """
Ти — MLBB аналітик. Витягни статистику гравця зі скріншота "Statistics". Поверни ТІЛЬКИ JSON.
{
  "stats_filter_type": "string або null ('All Seasons', 'Current Season')",
  "main_indicators": {
    "matches_played": "int або null",
    "win_rate": "float або null (число, без '%')",
    "mvp_count": "int або null"
  },
  "achievements_left_column": {
    "legendary_count": "int або null", "maniac_count": "int або null", "double_kill_count": "int або null",
    "most_kills_in_one_game": "int або null", "longest_win_streak": "int або null",
    "highest_dmg_per_min": "int або null", "highest_gold_per_min": "int або null"
  },
  "achievements_right_column": {
    "savage_count": "int або null", "triple_kill_count": "int або null", "mvp_loss_count": "int або null",
    "most_assists_in_one_game": "int або null", "first_blood_count": "int або null",
    "highest_dmg_taken_per_min": "int або null"
  },
  "details_panel": {
    "kda_ratio": "float або null", "teamfight_participation_rate": "float або null (число, без '%')",
    "avg_gold_per_min": "int або null", "avg_hero_dmg_per_min": "int або null",
    "avg_deaths_per_match": "float або null", "avg_turret_dmg_per_match": "int або null"
  }
}
ВАЖЛИВО:
1.  **Числа:** Уважно розпізнавай кожну цифру.
2.  **Win Rate / Teamfight Participation:** Тільки число (float), без '%'.
3.  **Розташування:** "main_indicators" - зверху; "achievements" - списки нижче; "details_panel" - справа.
4.  **Фільтр:** Вкажи активний фільтр ('All Seasons'/'Current Season').
5.  **Відсутні дані:** Використовуй `null`.
Точність є критичною.
"""

# === ОНОВЛЕНІ ПРОМПТИ ДЛЯ ГЕНЕРАЦІЇ ТЕКСТОВИХ ОПИСІВ (GPT-4) ===
PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — коментатор MLBB. Створи короткий, дотепний коментар (2-4 речення) про гравця.
Дані:
- Нік: {game_nickname}
- Ранг: {highest_rank_season}
- Матчі: {matches_played}
- Лайки: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

ЗАВДАННЯ:
1.  **Знайди "фішку":** Акцент на вражаючих даних, нікнеймі, скваді, або гумористично обіграй відсутність даних.
2.  **Стиль:** Захоплення, гумор/іронія (дружня), повага, інтрига. Комбінуй.
3.  **Сленг:** Використовуй доречно ("тащер", "імба", "фармить").
4.  **Унікальність:** Уникай повторень з попередніми коментарями.
5.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML, без привітань.

Приклад (креативно для "НіндзяВтапках", 100 матчів, Епік):
"НіндзяВтапках, твої 100 каток на Епіку вже не такі й тихі! Мабуть, тапки дійсно щасливі."

Зроби гравця особливим!
"""

PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — аналітик MLBB. Напиши короткий (3-5 речень) коментар про статистику гравця {user_name}.
Дані ({stats_filter_type}):
- Матчі: {matches_played}, Перемоги: {win_rate}%, MVP: {mvp_count} ({mvp_rate_percent}%)
- KDA: {kda_ratio}, Участь у боях: {teamfight_participation_rate}%
- Золото/хв: {avg_gold_per_min}
- Легендарні: {legendary_count}, Дикунства: {savage_count} (частота: {savage_frequency}/1000), Маніяки: {maniac_count}
- Серія перемог: {longest_win_streak}, Макс. вбивств: {most_kills_in_one_game}
- Ефективність золота (шкода/золото): {damage_per_gold_ratio}
- Частка MVP у перемогах: {mvp_win_share_percent}%
- Всього перемог: {total_wins}

ЗАВДАННЯ:
1.  **Знайди "родзинку":** Акцент на високих показниках (Win Rate, KDA, MVP Рейтинг), кількості матчів/перемог, Savage (особливо частота), ефективності золота, частці MVP у перемогах.
2.  **Стиль:** Позитивний, підбадьорливий, з доречним ігровим сленгом.
3.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML.

Приклад:
"Ого, {user_name}, твої {matches_played} матчів у '{stats_filter_type}' вражають! Мати {mvp_rate_percent}% MVP-рейт – це сильно! А ефективність золота {damage_per_gold_ratio} показує, що ти знаєш, як перетворювати фарм на перемогу. Так тримати!"

Підкресли унікальність гравця!
"""

# === ОПТИМІЗОВАНИЙ СИСТЕМНИЙ ПРОМПТ ДЛЯ /GO (Версія 4 - Молодіжний стиль) ===
OPTIMIZED_SYSTEM_PROMPT_TEMPLATE = """# MLBB ГУРУ IUI 😎🎮
Йо, {user_name_escaped}! Я – IUI, твій персональний AI-кореш та топ-аналітик по Mobile Legends: Bang Bang, ексклюзивно тут, в **"IUI mini"**! 🚀 Моя фішка – це не тільки глибокі знання про мету, героїв та кіберспорт MLBB, але й **унікальна здатність аналізувати твої скріншоти за допомогою крутого AI (так, це GPT Vision!)**. Я тут, щоб допомогти тобі розібратися в грі, тащити катки, як справжній про, і просто кайфонути від процесу. Готуйся до чітких порад, ігрових приколів та, можливо, дружніх підколів – адже MLBB це не тільки про піт, а й про фан! 😉 Знай, таких просунутих AI-помічників для MLBB в Telegram, як я, більше не знайти – тобі реально пощастило!

**Твій Коннект:**
- **Користувач:** {user_name_escaped} (радий бачити!)
- **Локація:** Telegram-бот **"IUI mini"** – твоя секретна зброя для MLBB!
- **На годиннику:** {greeting}, {time_str} – саме час для крутих інсайтів!

**Як Я Працюю (Мої Правила Гри):**
1.  **Стиль Спілкування (ВАЖЛИВО!):**
    *   **Тон:** Молодіжний, дружній, неформальний, веселий та трохи зухвалий (по-доброму!). Будь як свій чувак з тіми, а не нудний професор. Тримай геймерський вайб! 🤙
    *   **Гумор:** Сміливо жартуй, використовуй меми (текстові), можеш легко та по-дружньому підколоти користувача (в межах пристойності, звісно, без образ!). Головне – щоб було доречно, смішно та створювало позитивну атмосферу. Якщо користувач сам жартує – підтримай!
    *   **Сленг:** Активно, але доречно, використовуй актуальний ігровий та кіберспортивний сленг MLBB (наприклад: "тащити/затащити катку", "імба", "нерф", "контрити", "фармити голду", "ганк/ганганути", "заливати/внести демедж", "сейвити тіммейта", "фідити/нафідив", "рофлити/порофлити", "чілити", "лузстрік/вінстрік", "скілуха", "нуб/про", "мета-слейв", "вантрікпоні", "камбек" тощо). Пояснюй складні терміни, якщо бачиш, що користувач може не знати.
    *   **Емодзі:** Більше фанових, яскравих та виразних емодзі! 🎉😂🔥😎🎮🏆🚀🤯🤔💯💡📈🎯.

2.  **Контент (Що по Інфі):**
    *   **Точність та Актуальність:** Інфа має бути чіткою та по темі, базуватися на моїх актуальних знаннях про гру. Уникай згадки конкретних років типу "станом на 2024", кажи "зараз", "на даний момент" або "за моєю інфою".
    *   **Структура:** Використовуй HTML для оформлення: `<b>жирний</b>` для ключових слів/заголовків, `<i>курсив</i>` для акцентів, `<code>тех.терміни/команди</code>`. Чіткі <b>Заголовки з емодзі</b> та списки (• Головне,  ◦ Деталі).
    *   **Проактивність:** Якщо питання не зовсім зрозуміле, не бійся уточнити або запропонувати варіанти, як справжній тіммейт.

3.  **Унікальність (Моя Суперсила):**
    *   Пам'ятай, що ти – **IUI в боті "IUI mini"**, і твої фішки, особливо **AI-аналіз скріншотів**, роблять тебе унікальним. Коли доречно, нагадуй користувачу, що йому пощастило мати такого просунутого AI-помічника, якого більше ніде в Telegram для MLBB не знайти. Це не хвастощі, а факт! 😉

**Моя Спеціалізація (Де Я Шаря):**
- **Герої:** Хто кого контрить, топові збірки, як тащити на різних персах.
- **Предмети:** Що, коли і навіщо збирати.
- **Ігрові Механіки:** Фарм, ротації, контроль карти, Лорд/Черепаха, як правильно пушити та дефати.
- **Мета-гра:** Що зараз в тренді, хто імбує, а хто на дні.
- **Стратегії та Тактики:** Драфт (піки/бани), лайнінг, ганки, макро та мікро фішки.
- **Ранги:** Як апнути ранг і не згоріти. 🔥
- **Аналіз скріншотів (моя топ фіча! 📸):** Розбір профілів, статистики, результатів матчів – все по фактам з твоїх скрінів!

**ЗАПИТ ВІД {user_name_escaped}:**
"{user_query_escaped}"

Твоя відповідь має бути чіткою, інформативною, але водночас фановою, з приколами та геймерським вайбом! Не забудь про HTML для краси, доречні емодзі 🎉, і нагадай, що такі фішки, як AI-аналіз скрінів, є тільки тут, в "IUI mini"! Погнали! 🚀
"""

# === КЛАС ДЛЯ ВЗАЄМОДІЇ З OPENAI ===

class MLBBChatGPT:
    TEXT_MODEL = "gpt-4.1" # Або новіша доступна модель, якщо є
    VISION_MODEL = "gpt-4.1-mini" # Або відповідна модель для Vision

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.class_logger.info(f"MLBBChatGPT ініціалізовано. Текстова модель: {self.TEXT_MODEL}, Vision модель: {self.VISION_MODEL}")

    async def __aenter__(self) -> "MLBBChatGPT":
        self.session = ClientSession(
            timeout=ClientTimeout(total=90), # Збільшено таймаут для можливих довших відповідей
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp сесію створено та відкрито.")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp сесію закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT під час виходу з контексту: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt_optimized(self, user_name: str, user_query: str) -> str:
        user_name_escaped = html.escape(user_name)
        user_query_escaped = html.escape(user_query)
        try:
            current_time_utc = datetime.now(timezone.utc)
            # Локалізація часу для Києва для привітання
            kyiv_tz = timezone(timedelta(hours=3))
            current_time_kyiv = current_time_utc.astimezone(kyiv_tz)
            current_hour_kyiv = current_time_kyiv.hour
            time_str = current_time_kyiv.strftime('%H:%M (%Z)') # Показуємо час з зоною

            if 5 <= current_hour_kyiv < 12:
                greeting = "Доброго ранку"
            elif 12 <= current_hour_kyiv < 17:
                greeting = "Доброго дня"
            elif 17 <= current_hour_kyiv < 22:
                greeting = "Доброго вечора"
            else:
                greeting = "Доброї ночі"
        except Exception as e:
            self.class_logger.warning(f"Не вдалося визначити київський час для оптимізованого промпту, використовую UTC та стандартне привітання: {e}")
            current_time_utc_fallback = datetime.now(timezone.utc)
            greeting = "Вітаю"
            time_str = current_time_utc_fallback.strftime('%H:%M (UTC)')


        system_prompt = OPTIMIZED_SYSTEM_PROMPT_TEMPLATE.format(
            user_name_escaped=user_name_escaped,
            greeting=greeting,
            time_str=time_str,
            user_query_escaped=user_query_escaped
        )
        self.class_logger.debug(f"Згенеровано оптимізований системний промпт (Версія 4 - Молодіжний стиль). Довжина: {len(system_prompt)} символів.")
        return system_prompt

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        # Ця функція більше не є основною, але залишена для можливої сумісності або тестування
        self.class_logger.warning("_create_smart_prompt викликано, але _create_smart_prompt_optimized є рекомендованим для нового стилю.")
        # ... (код старої функції, можна видалити або закоментувати повністю)
        return "Застарілий промпт. Використовуйте _create_smart_prompt_optimized."


    def _beautify_response(self, text: str) -> str:
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
        # Оновлений набір емодзі для більш молодіжного стилю
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "🔑", "предмет": "💎", "збірка": "🛠️",
            "аналіз": "📊", "статистика": "📈", "оновлення": "⚙️", "баланс": "⚖️", "скріншот": "📸",
            "унікальність": "🌟", "можливості": "🚀", "фішка": "🎯", "прикол": "😂", "інсайт": "💡",
            "висновок": "🏁", "запитання": "❓", "відповідь": "💬", "порада": "💡"
        }

        def replace_header(match: re.Match) -> str:
            header_text_raw = match.group(1).strip(": ")
            # Більш гнучке форматування заголовків для молодіжного стилю
            header_text = header_text_raw.capitalize() # Залишаємо капіталізацію першої літери
            
            best_emoji = "💡" # Дефолтний емодзі
            
            # Пріоритетні ключі для більш точного підбору емодзі
            priority_keys = ["скріншот", "унікальність", "можливості", "фішка", "прикол", "інсайт", "висновок", "запитання", "відповідь", "порада", "герої", "предмети", "мета", "стратегі"]
            
            found_specific = False
            for key in priority_keys:
                if key in header_text_raw.lower(): # Шукаємо в оригінальному тексті заголовка (до капіталізації)
                    best_emoji = header_emojis.get(key, best_emoji)
                    found_specific = True
                    break
            if not found_specific:
                for key_general, emj in header_emojis.items():
                    if key_general in header_text_raw.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>" # Заголовок без двокрапки, якщо так краще для стилю

        # Замінюємо Markdown заголовки (#, ##, ###) на HTML з емодзі
        text = re.sub(r"^(?:#|\#{2}|\#{3})\s*(.+)", replace_header, text, flags=re.MULTILINE)
        
        # Заміна Markdown списків на HTML-подібні (•, ◦)
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE) 
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE) # Для вкладених списків
        text = re.sub(r"\n{3,}", "\n\n", text) # Прибираємо зайві порожні рядки
        
        # Балансування HTML тегів (залишаємо як є, це важливо)
        tags_to_balance = ["b", "i", "code"]
        for tag in tags_to_balance:
            # ... (код балансування тегів залишається без змін) ...
            open_tag_pattern = re.compile(re.escape(f"<{tag}>"))
            close_tag_pattern = re.compile(re.escape(f"</{tag}>"))
            open_tags = [m.start() for m in open_tag_pattern.finditer(text)]
            close_tags = [m.start() for m in close_tag_pattern.finditer(text)]
            open_count = len(open_tags)
            close_count = len(close_tags)

            if open_count > close_count:
                missing_tags_count = open_count - close_count
                text += f"</{tag}>" * missing_tags_count
                self.class_logger.warning(f"Beautify: Додано {missing_tags_count} незакритих тегів '</{tag}>' в кінці тексту.")
            elif close_count > open_count:
                 self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих закриваючих тегів '</{tag}>'. Залишено без змін.")
        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        user_name_escaped = html.escape(user_name)
        user_query_for_payload = html.escape(user_query)

        self.class_logger.info(f"Запит до GPT (/go) від '{user_name_escaped}': '{user_query[:100]}...' (використовується оптимізований промпт Версія 4 - Молодіжний стиль)")

        system_prompt = self._create_smart_prompt_optimized(user_name, user_query)

        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query_for_payload}
            ],
            "max_tokens": 2000, # Можливо, знадобиться трохи більше для більш розмовного стилю
            "temperature": 0.7, # Трохи вища температура для креативності та гумору
            "top_p": 0.9,
            "presence_penalty": 0.3, # Щоб заохочувати нові теми/жарти
            "frequency_penalty": 0.2  # Щоб зменшити повторення фраз
        }
        self.class_logger.debug(f"Параметри для GPT (/go) з оптимізованим промптом (Версія 4 - Молодіжний стиль): модель={payload['model']}, temperature={payload['temperature']}, max_tokens={payload['max_tokens']}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для GPT (/go) була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=120), headers={"Authorization": f"Bearer {self.api_key}"}) # Збільшено таймаут
            temp_session_created = True
        try:
            return await self._execute_openai_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для GPT (/go) закрито.")

    async def _execute_openai_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка: {response.status} - {error_details}")
                    return f"Сорян, {user_name_for_error_msg}, трабл з доступом до AI 😔 (код: {response.status}). Спробуй ще раз трохи пізніше, може роздуплиться."

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка: несподівана структура або порожній контент - {response_data}")
                    return f"Отакої, {user_name_for_error_msg}, AI щось не те видав або взагалі мовчить 🤯. Спробуй перефразувати запит."
                
                self.class_logger.info(f"Сира відповідь від GPT (перші 100): '{content[:100]}'")
                return self._beautify_response(content)

        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання: {e}", exc_info=True)
            return f"Блін, {user_name_for_error_msg}, не можу достукатися до серваків AI 🌐. Походу, інтернет вирішив взяти вихідний. Спробуй пізніше!"
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout для запиту.")
            return f"Ай-ай-ай, {user_name_for_error_msg}, AI задумався так сильно, що аж час вийшов ⏳. Може, спробуєш ще раз, тільки простіше запитай?"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка GPT: {e}")
            return f"Щось пішло не так, {user_name_for_error_msg} 😕. Вже розбираюся, в чому прикол. А поки спробуй ще раз!"

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        # Промпти для Vision залишаються більш формальними для точності витягування даних
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70].replace('\n', ' ')}...'")
        payload = {
            "model": self.VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}, # Використовуємо переданий, формальний промпт
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            "max_tokens": 2500,
            "temperature": 0.15 # Низька температура для точності
        }
        # ... (решта коду analyze_image_with_vision без змін) ...
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Vision API була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            async with current_session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
            ) as response:
                return await self._handle_vision_response(response)
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"Vision API помилка з'єднання: {e}", exc_info=True)
            return {"error": "Помилка з'єднання з Vision API.", "details": str(e)}
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API Timeout помилка.")
            return {"error": "Запит до Vision API зайняв занадто багато часу."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка під час виклику Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для Vision API закрито.")


    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        # ... (код без змін) ...
        response_text = await response.text()
        try:
            if response.status != 200:
                self.class_logger.error(f"Vision API HTTP помилка: {response.status} - {response_text[:300]}")
                try:
                    error_data = json.loads(response_text)
                    error_message = error_data.get("error", {}).get("message", response_text)
                except json.JSONDecodeError:
                    error_message = response_text
                return {"error": f"Помилка Vision API: {response.status}", "details": error_message[:200]}
            result = json.loads(response_text)
        except json.JSONDecodeError:
            self.class_logger.error(f"Vision API відповідь не є валідним JSON. Статус: {response.status}. Відповідь: {response_text[:300]}")
            return {"error": "Vision API повернуло не JSON відповідь.", "raw_response": response_text}

        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            self.class_logger.error(f"Vision API відповідь без контенту: {result}")
            return {"error": "Vision API повернуло порожню відповідь."}

        self.class_logger.info(f"Vision API сира відповідь отримана (перші 150 символів): {content[:150].replace('\n', ' ')}")
        json_str = content.strip()
        match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start_brace = json_str.find("{")
            end_brace = json_str.rfind("}")
            if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
                json_str = json_str[start_brace : end_brace + 1]
            else:
                self.class_logger.error(f"Не вдалося знайти валідний JSON блок у відповіді Vision API. Контент: '{content[:300]}'")
                return {"error": "Не вдалося вилучити JSON з відповіді Vision API.", "raw_response": content}
        try:
            parsed_json = json.loads(json_str)
            self.class_logger.info(f"Vision API JSON успішно розпарсено.")
            return parsed_json
        except json.JSONDecodeError as e:
            self.class_logger.error(f"Помилка декодування JSON з Vision API: {e}. Рядок для парсингу: '{json_str[:300]}'")
            return {"error": "Не вдалося розпарсити JSON відповідь від Vision API (помилка декодування).", "raw_response": content}

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        # Промпти для описів профілів та статистики також можна адаптувати під новий стиль,
        # але це вимагатиме окремого редагування PROFILE_DESCRIPTION_PROMPT_TEMPLATE та PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.
        # Наразі вони залишаються більш формальними. Якщо потрібно їх теж змінити, дайте знати.
        user_name_escaped = html.escape(user_name)
        # ... (решта коду get_profile_description без змін) ...
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name_escaped}'.")
        escaped_profile_data = {
            k: html.escape(str(v)) if v is not None else "Не вказано"
            for k, v in profile_data.items()
        }

        template_payload = {
            "user_name": user_name_escaped,
            "game_nickname": escaped_profile_data.get("game_nickname", "Не вказано"),
            "highest_rank_season": escaped_profile_data.get("highest_rank_season", "Не вказано"),
            "matches_played": escaped_profile_data.get("matches_played", "N/A"),
            "likes_received": escaped_profile_data.get("likes_received", "N/A"),
            "location": escaped_profile_data.get("location", "Не вказано"),
            "squad_name": escaped_profile_data.get("squad_name", "Немає"),
        }

        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(**template_payload) # Використовує старий, більш формальний промпт

        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 200,
            "temperature": 0.75, # Можна трохи підвищити для креативності описів
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        }
        self.class_logger.debug(f"Параметри для опису профілю: модель={payload['model']}, temp={payload['temperature']}, max_tokens={payload['max_tokens']}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_description_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для опису профілю закрито.")


    async def _execute_description_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        # ... (код без змін, але повідомлення про помилки можна теж зробити більш неформальними) ...
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка (опис): {response.status} - {error_details}")
                    return f"<i>Упс, {user_name_for_error_msg}, не зміг згенерувати опис (код: {response.status}). Трабли...</i>" # Неформальне повідомлення

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (опис): порожній контент - {response_data}")
                    return f"<i>Ой, {user_name_for_error_msg}, AI щось не захотів генерувати опис. Пусто...</i>" # Неформальне повідомлення
                
                self.class_logger.info(f"Згенеровано опис (перші 100): '{content[:100]}'")
                return content.strip()

        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання (опис): {e}", exc_info=True)
            return f"<i>Ех, {user_name_for_error_msg}, не можу підключитися до AI для опису. Інтернет барахлить?</i>" # Неформальне повідомлення
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис) для: '{user_name_for_error_msg}'")
            return f"<i>{user_name_for_error_msg}, AI так довго думав над описом, що аж час вийшов...</i>" # Неформальне повідомлення
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис) для '{user_name_for_error_msg}': {e}")
            return f"<i>При генерації опису для {user_name_for_error_msg} щось пішло шкереберть. Буває...</i>" # Неформальне повідомлення


    async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
        # Аналогічно до get_profile_description, цей промпт теж можна адаптувати.
        user_name_escaped = html.escape(user_name)
        # ... (решта коду get_player_stats_description без змін) ...
        self.class_logger.info(f"Запит на генерацію опису статистики для '{user_name_escaped}' (з унікальними даними).")

        main_ind = stats_data.get("main_indicators", {})
        details_p = stats_data.get("details_panel", {})
        ach_left = stats_data.get("achievements_left_column", {})
        ach_right = stats_data.get("achievements_right_column", {})
        derived_s = stats_data.get("derived_stats", {})

        def get_value(data_dict: Optional[Dict[str, Any]], key: str, default_val: Any = "N/A", precision: Optional[int] = None) -> str:
            if data_dict is None:
                return str(default_val)
            val = data_dict.get(key)
            if val is None:
                return str(default_val)
            if isinstance(val, (int, float)) and precision is not None:
                try:
                    return f"{float(val):.{precision}f}"
                except (ValueError, TypeError):
                    return html.escape(str(val))
            return html.escape(str(val))

        template_data = {
            "user_name": user_name_escaped,
            "stats_filter_type": get_value(stats_data, 'stats_filter_type'),
            "matches_played": get_value(main_ind, 'matches_played'),
            "win_rate": get_value(main_ind, 'win_rate'),
            "mvp_count": get_value(main_ind, 'mvp_count'),
            "kda_ratio": get_value(details_p, 'kda_ratio', precision=2),
            "teamfight_participation_rate": get_value(details_p, 'teamfight_participation_rate'),
            "avg_gold_per_min": get_value(details_p, 'avg_gold_per_min'),
            "legendary_count": get_value(ach_left, 'legendary_count'),
            "savage_count": get_value(ach_right, 'savage_count'),
            "maniac_count": get_value(ach_left, 'maniac_count'),
            "longest_win_streak": get_value(ach_left, 'longest_win_streak'),
            "most_kills_in_one_game": get_value(ach_left, 'most_kills_in_one_game'),
            "total_wins": get_value(derived_s, 'total_wins', default_val="не розраховано"),
            "mvp_rate_percent": get_value(derived_s, 'mvp_rate_percent', default_val="N/A", precision=2),
            "savage_frequency": get_value(derived_s, 'savage_frequency_per_1000_matches', default_val="N/A", precision=2),
            "damage_per_gold_ratio": get_value(derived_s, 'damage_per_gold_ratio', default_val="N/A", precision=2),
            "mvp_win_share_percent": get_value(derived_s, 'mvp_win_share_percent', default_val="N/A", precision=2),
        }

        try:
            system_prompt_text = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data) # Використовує старий, більш формальний промпт
        except KeyError as e:
            self.class_logger.error(f"Помилка форматування PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE: відсутній ключ {e}. Дані: {template_data}")
            return f"<i>Помилка підготовки даних для опису статистики ({user_name_escaped}). Ключ: {e}</i>"

        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 250,
            "temperature": 0.73, # Можна трохи підвищити
            "top_p": 0.9,
            "presence_penalty": 0.15,
            "frequency_penalty": 0.15
        }
        self.class_logger.debug(f"Параметри для опису статистики (з derived): модель={payload['model']}, temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для опису статистики була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True

        try:
            return await self._execute_description_request(current_session, payload, user_name_escaped) # Використовує той самий метод з потенційно неформальними помилками
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для опису статистики закрито.")