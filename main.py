import os
import asyncio
import logging
import requests
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from fastapi import FastAPI
import uvicorn

# Загрузка переменных окружения (для локального тестирования)
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("APPLICATION_ID")
USER_ID = os.getenv("USER_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
MAL_USERNAME = os.getenv("MAL_USERNAME")

# Инициализация логирования и веб-сервера FastAPI для Render
logging.basicConfig(level=logging.INFO)
app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Bot is running perfectly"}

# Инициализация Discord-бота (настройка интентов)
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.tree.command(name="setup_widget", description="Авторизовать приложение для работы виджета")
async def setup_widget(interaction: discord.Interaction):
    auth_url = (
        "https://discord.com/oauth2/authorize"
        f"?client_id={APPLICATION_ID}"
        "&response_type=token"
        "&scope=openid+sdk.social_layer"
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Authorize", style=discord.ButtonStyle.link, url=auth_url))
    await interaction.response.send_message(
        "Нажми кнопку ниже и авторизуй приложение (можно сразу закрыть открывшуюся страницу после подтверждения). "
        "После этого запусти `/refresh_widget`.",
        view=view,
        ephemeral=True
    )

def get_github_commits() -> int:
    """Парсинг общего количества коммитов пользователя с GitHub API."""
    url = f"https://api.github.com/search/commits?q=author:{GITHUB_USERNAME}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 1.0.0)",
        "Authorization": f"Bearer {GITHUB_TOKEN}" if GITHUB_TOKEN else ""
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("total_count", 0)
        logging.error(f"GitHub API Error {response.status_code}: {response.text}")
    except Exception as e:
        logging.error(f"Failed to fetch GitHub commits: {e}")
    return 0

def get_mal_stats() -> tuple[int, int]:
    """Парсинг количества просмотренных тайтлов и часов из MyAnimeList через Jikan API."""
    url = f"https://api.jikan.moe/v4/users/{MAL_USERNAME}/full"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            anime_stats = response.json().get("data", {}).get("statistics", {}).get("anime", {})
            completed = anime_stats.get("completed", 0)
            days_watched = anime_stats.get("days_watched", 0.0)
            hours = int(days_watched * 24)  # Переводим дни в часы
            return completed, hours
    except Exception as e:
        logging.error(f"Failed to fetch MAL stats: {e}")
    return 0, 0

def update_discord_widget() -> bool:
    """Сборщик данных и отправка PATCH-запроса для обновления виджета."""
    commits = get_github_commits()
    anime_count, anime_hours = get_mal_stats()

    # Ссылка из гайда для обновления конкретного профиля
    url = f"https://discord.com/api/v9/applications/{APPLICATION_ID}/users/{USER_ID}/identities/0/profile"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "User-Agent": "DiscordBot (https://github.com, 1.0.0)"
    }

    # Полезная нагрузка. Названия полей (name) должны строго совпадать с тем, что ты указал в Developer Portal
    payload = {
        "username": "SevaGetz",
        "data": {
            "dynamic": [
                { "type": 1, "name": "subtitle_1", "value": f"GitHub: {commits} Commits" },
                { "type": 1, "name": "subtitle_2", "value": f"Anime: {anime_count} Titles" },
                { "type": 1, "name": "subtitle_3", "value": f"Time: {anime_hours} Hours" }
            ]
        }
    }

    try:
        res = requests.patch(url, json=payload, headers=headers, timeout=10)
        if res.status_code in [200, 204]:
            logging.info("Widget updated successfully!")
            return True
        logging.error(f"Discord Widget API Error {res.status_code}: {res.text}")
    except Exception as e:
        logging.error(f"Failed to patch Discord widget: {e}")
    return False

# Фоновая задача: авто-обновление виджета раз в 1 час
@tasks.loop(hours=1)
async def auto_update_widget():
    logging.info("Running scheduled widget update...")
    # Запускаем в отдельном потоке, чтобы не блокировать асинхронный цикл бота синхронным requests
    await asyncio.to_thread(update_discord_widget)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    # Регистрация слэш-команд
    try:
        await bot.tree.sync()
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
    
    # Запуск циклической задачи, если она еще не запущена
    if not auto_update_widget.is_running():
        auto_update_widget.start()

@bot.tree.command(name="refresh_widget", description="Принудительно обновить данные виджета профиля")
async def refresh_widget(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    success = await asyncio.to_thread(update_discord_widget)
    if success:
        await interaction.followup.send("Виджет успешно обновлен!", ephemeral=True)
    else:
        await interaction.followup.send("Произошла ошибка при обновлении виджета. Проверь логи.", ephemeral=True)

# Функция одновременного запуска FastAPI и Discord-бота
async def main():
    # Запускаем FastAPI сервер uvicorn на фоне
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
    server = uvicorn.Server(config)
    
    # asyncio.gather позволяет параллельно крутить веб-сервер и бота
    await asyncio.gather(
        server.serve(),
        bot.start(DISCORD_TOKEN)
    )

if __name__ == "__main__":
    asyncio.run(main())
