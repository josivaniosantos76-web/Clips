# -*- coding: utf-8 -*-
import os
import subprocess
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'workspace'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def tirar_silencio_inicial(caminho_video, parte_num):
    """Garante que o corte comece exatamente no primeiro milissegundo de fala"""
    try:
        audio_temp = f"temp_audio_{parte_num}.wav"
        subprocess.run(['ffmpeg', '-y', '-i', caminho_video, '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', audio_temp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        sound = AudioSegment.from_file(audio_temp, format="wav")
        silence_threshold = -40 # Limiar de silêncio em dB
        inicio_fala_ms = detect_leading_silence(sound, silence_threshold=silence_threshold)
        
        os.remove(audio_temp)
        
        if inicio_fala_ms > 0:
            inicio_segundos = inicio_fala_ms / 1000.0
            print(f"[AUDIO] Cortando {inicio_segundos}s de silêncio na Parte {parte_num}")
            video_ajustado = caminho_video.replace('.mp4', '_fala.mp4')
            subprocess.run(['ffmpeg', '-y', '-ss', str(inicio_segundos), '-i', caminho_video, '-c', 'copy', video_ajustado], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(caminho_video)
            os.rename(video_ajustado, caminho_video)
    except Exception as e:
        print(f"[Aviso] Falha ao remover silêncio: {e}")

@app.route('/processar', methods=['POST'])
def processar_cortes():
    try:
        video_url = request.form.get('url')
        quantidade_cortes = int(request.form.get('quantidade', 20))
        tempo_corte = int(request.form.get('tempo', 30))
        texto_topo = request.form.get('texto_topo', '').upper()
        texto_baixo = request.form.get('texto_baixo', '').upper()
        
        imagem_fundo = request.files.get('fundo')
        musica_fundo = request.files.get('musica') # Nova trilha opcional
        
        if not video_url or not imagem_fundo:
            return jsonify({"erro": "Faltam dados essenciais"}), 400
            
        bg_path = os.path.join(UPLOAD_FOLDER, 'fundo.png')
        imagem_fundo.save(bg_path)
        
        audio_bg_path = None
        if musica_fundo:
            audio_bg_path = os.path.join(UPLOAD_FOLDER, 'musica.mp3')
            musica_fundo.save(audio_bg_path)
        
        video_original = os.path.join(UPLOAD_FOLDER, 'downloaded.mp4')
        url_limpa = video_url.split('?')[0] if 'youtu.be' in video_url else video_url
        
        print("[SERVER] Extraindo mídia do YouTube...")
        subprocess.run([
            'yt-dlp', '--no-check-certificates', '--prefer-free-formats',
            '-f', 'mp4', '-o', video_original, url_limpa
        ], check=True)
        
        # Limpeza de workspace
        for f in os.listdir(UPLOAD_FOLDER):
            if f.startswith('corte_') and f.endswith('.mp4'):
                os.remove(os.path.join(UPLOAD_FOLDER, f))

        # CONSTRUÇÃO DO FILTRO AVANÇADO FFMPEG (1:1 + Fundo 9:16 + Escudo Anti-Copyright + Textos)
        # Saturação alterada levemente e zoom de 1.01x imperceptível para o olho humano
        filtro_video = (
            '[0:v]scale=1080:1080,setsar=1,eq=saturation=1.02,scale=1.01*iw:-1,crop=1080:1080[vid]; '
            '[1:v]scale=1080:1920[bg]; [bg][vid]overlay=(W-w)/2:(H-h)/2[base]'
        )
        
        # Inserção de Textos Estilizados
        filtros_texto = []
        if texto_topo:
            filtros_texto.append(f"drawtext=text='{texto_topo}':fontcolor=white:fontsize=64:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:x=(w-text_w)/2:y=200")
        if texto_baixo:
            filtros_texto.append(f"drawtext=text='{texto_baixo}':fontcolor=yellow:fontsize=54:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:x=(w-text_w)/2:y=1650")
            
        if filtros_texto:
            filtro_video += f"; [base]" + ",".join(filtros_texto) + "[outv]"
        else:
            filtro_video += "; [base]null[outv]"

        # Mixagem de Áudio (Voz Original + Trilha Sonora Opcional a 15% de Volume)
        comando_ffmpeg = ['ffmpeg', '-y', '-i', video_original, '-i', bg_path]
        
        if audio_bg_path:
            comando_ffmpeg += ['-i', audio_bg_path]
            filtro_audio = "[0:a]volume=1.0[v_orig]; [2:a]volume=0.15[v_trilha]; [v_orig][v_trilha]amix=inputs=2:duration=first[outa]"
        else:
            filtro_audio = "[0:a]amix=inputs=1[outa]"
            
        comando_ffmpeg += [
            '-filter_complex', f"{filtro_video}; {filtro_audio}",
            '-map', '[outv]', '-map', '[outa]',
            '-f', 'segment', '-segment_time', str(tempo_corte),
            '-c:v', 'libx264', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            os.path.join(UPLOAD_FOLDER, 'corte_%03d.mp4')
        ]
        
        print("[SERVER] Renderizando lote inteligente...")
        subprocess.run(comando_ffmpeg, check=True)
        
        # Pós-processamento: Cortar o silêncio de cada bloco gerado
        todos_cortes = sorted([f for f in os.listdir(UPLOAD_FOLDER) if f.startswith('corte_')])
        cortes_finais = todos_cortes[:quantidade_cortes]
        
        for idx, corte in enumerate(cortes_finais):
            caminho_corte = os.path.join(UPLOAD_FOLDER, corte)
            tirar_silencio_inicial(caminho_corte, idx)
            
        return jsonify({"sucesso": True, "videos": cortes_finais})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
      
