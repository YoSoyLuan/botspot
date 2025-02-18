import os
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler
from telegram.ext import filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import urllib.parse
import yt_dlp
import logging
from config import TELEGRAM_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Directorio de descargas
DOWNLOAD_PATH = 'downloads'

# Configuración mejorada de yt-dlp
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
    'extract_flat': False,
    'ignoreerrors': False,
    'logtostderr': False,
    'retries': 5,
    'fragment_retries': 5,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
}

class SpotifyBot:
    def __init__(self):
        self.spotify = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET
            )
        )
        self.ensure_download_directory()

    def ensure_download_directory(self):
        if not os.path.exists(DOWNLOAD_PATH):
            os.makedirs(DOWNLOAD_PATH)
        else:
            self.clean_download_directory()

    def clean_download_directory(self):
        for file in os.listdir(DOWNLOAD_PATH):
            try:
                file_path = os.path.join(DOWNLOAD_PATH, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Error limpiando archivo {file}: {str(e)}")

    async def search_youtube(self, title):
        search_query = f"{title} audio official"
        youtube_query = f"ytsearch1:{urllib.parse.quote(search_query)}"
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_query, download=False)
                if not info.get('entries'):
                    return None
                video_info = info['entries'][0]
                return {
                    'url': video_info['webpage_url'],
                    'title': video_info['title']
                }
        except Exception as e:
            logger.error(f"Error en búsqueda de YouTube: {str(e)}")
            return None

    async def download_track(self, video_info):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_info['url']])
                mp3_files = [f for f in os.listdir(DOWNLOAD_PATH) if f.endswith('.mp3')]
                if not mp3_files:
                    return None
                return os.path.join(DOWNLOAD_PATH, mp3_files[0])
        except Exception as e:
            logger.error(f"Error en descarga: {str(e)}")
            return None

    async def download_and_send_track(self, track_id, message, status_message):
        try:
            track_info = self.spotify.track(track_id)
            title = f"{track_info['artists'][0]['name']} - {track_info['name']}"
            
            self.clean_download_directory()
            
            await status_message.edit_text(f"🔍 Buscando: {title}")
            
            video_info = await self.search_youtube(title)
            if not video_info:
                await status_message.edit_text("❌ No se encontró la canción en YouTube.")
                return
            
            await status_message.edit_text("⏬ Descargando...")
            file_path = await self.download_track(video_info)
            
            if file_path and os.path.exists(file_path):
                await status_message.edit_text("📤 Enviando archivo...")
                
                # Enviar el archivo de audio
                await message.reply_audio(
                    audio=open(file_path, 'rb'),
                    title=track_info['name'],
                    performer=track_info['artists'][0]['name'],
                    caption=f"🎵 {title}\n🎼 Álbum: {track_info['album']['name']}"
                )
                
                # Limpiar
                os.remove(file_path)
                await status_message.delete()
            else:
                raise Exception("No se pudo descargar el archivo")
                
        except Exception as e:
            logger.error(f"Error general: {str(e)}")
            await status_message.edit_text(
                "❌ No se pudo descargar la canción.\n"
                "Por favor, intenta con otra canción o más tarde."
            )

    async def start(self, update: Update, context):
        user_name = update.message.from_user.first_name
        welcome_text = (
            f'¡Hola {user_name}! 👋\n\n'
            'Puedo ayudarte a encontrar y descargar música. Usa:\n\n'
            '1. /search + nombre de la canción\n'
            '   Ejemplo: /search Bad Guy - Billie Eilish\n\n'
            '2. Pega un link de Spotify\n'
            '   Ejemplo: https://open.spotify.com/track/...\n\n'
            '📌 Usa /help para ver todos los comandos'
        )
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context):
        help_text = (
            '📚 Comandos disponibles:\n\n'
            '/search [nombre de la canción] - Busca una canción\n'
            'Ejemplo: /search Shape of You\n\n'
            '🔗 También puedes enviar un link de Spotify directamente\n\n'
            '✨ Tips:\n'
            '- Incluye el nombre del artista para mejores resultados\n'
            '- La búsqueda puede tardar unos segundos\n'
            '- Si una canción falla, intenta con otra'
        )
        await update.message.reply_text(help_text)

    async def search_command(self, update: Update, context):
        if not context.args:
            await update.message.reply_text(
                "❌ Por favor, escribe el nombre de la canción después de /search\n"
                "Ejemplo: /search Bad Guy - Billie Eilish"
            )
            return

        query = ' '.join(context.args)
        try:
            status_message = await update.message.reply_text("🔍 Buscando...")
            results = self.spotify.search(q=query, type='track', limit=5)
            
            if not results['tracks']['items']:
                await status_message.edit_text("❌ No encontré ninguna canción con ese nombre.")
                return

            keyboard = []
            for track in results['tracks']['items']:
                title = f"{track['artists'][0]['name']} - {track['name']}"
                keyboard.append([InlineKeyboardButton(
                    text=title[:64],
                    callback_data=f"track_{track['id']}"
                )])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_message.edit_text(
                "🎵 Selecciona una canción:",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Error en búsqueda: {str(e)}")
            await status_message.edit_text(
                "❌ Error durante la búsqueda. Por favor, intenta de nuevo."
            )

    async def button_callback(self, update: Update, context):
        query = update.callback_query
        await query.answer()
        
        try:
            track_id = query.data.split('_')[1]
            status_message = await query.message.edit_text("⏳ Procesando solicitud...")
            
            track_info = self.spotify.track(track_id)
            duration_min = int(track_info['duration_ms']/1000//60)
            duration_sec = int(track_info['duration_ms']/1000%60)
            
            await status_message.edit_text(
                f"🎵 Información de la canción:\n\n"
                f"🎤 Artista: {track_info['artists'][0]['name']}\n"
                f"🎼 Título: {track_info['name']}\n"
                f"💿 Álbum: {track_info['album']['name']}\n"
                f"⏱ Duración: {duration_min}:{duration_sec:02d}\n\n"
                f"⏳ Preparando descarga..."
            )
            
            await self.download_and_send_track(track_id, query.message, status_message)
            
        except Exception as e:
            logger.error(f"Error en callback: {str(e)}")
            await query.message.edit_text(
                "❌ Error al procesar la canción.\n"
                "Por favor, intenta de nuevo."
            )

    async def process_spotify_url(self, update: Update, context):
        url = update.message.text
        if not 'open.spotify.com/track' in url:
            return

        try:
            status_message = await update.message.reply_text('⏳ Procesando enlace...')
            track_id = url.split('track/')[1].split('?')[0]
            
            track_info = self.spotify.track(track_id)
            duration_min = int(track_info['duration_ms']/1000//60)
            duration_sec = int(track_info['duration_ms']/1000%60)
            
            await status_message.edit_text(
                f"🎵 Información de la canción:\n\n"
                f"🎤 Artista: {track_info['artists'][0]['name']}\n"
                f"🎼 Título: {track_info['name']}\n"
                f"💿 Álbum: {track_info['album']['name']}\n"
                f"⏱ Duración: {duration_min}:{duration_sec:02d}\n\n"
                f"⏳ Preparando descarga..."
            )
            
            await self.download_and_send_track(track_id, update.message, status_message)

        except Exception as e:
            logger.error(f"Error: {str(e)}")
            await status_message.edit_text(
                '❌ Error al procesar el enlace.\n'
                'Verifica que sea un enlace válido de Spotify.'
            )

def main():
    try:
        # Crear el directorio de descargas si no existe
        if not os.path.exists(DOWNLOAD_PATH):
            os.makedirs(DOWNLOAD_PATH)

        application = (
            Application.builder()
            .token(TELEGRAM_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .build()
        )

        bot = SpotifyBot()
        
        application.add_handler(CommandHandler("start", bot.start))
        application.add_handler(CommandHandler("help", bot.help_command))
        application.add_handler(CommandHandler("search", bot.search_command))
        application.add_handler(CallbackQueryHandler(bot.button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_spotify_url))
        
        print("✅ Bot iniciado correctamente")
        application.run_polling(drop_pending_updates=True)

    except Exception as e:
        print(f"❌ Error crítico: {str(e)}")
        logger.error(f"Error crítico: {str(e)}", exc_info=True)

if __name__ == '__main__':
    main()
