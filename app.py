# -*- coding: utf-8 -*-
import os
import subprocess
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'workspace'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def tirar_silencio_inicial(caminho_video, parte_num):
    """Detecta e remove o silêncio inicial usando apenas o FFmpeg nativo"""
    try:
        # Executa o filtro silencedetect do FFmpeg para achar onde o som começa
        comando_busca = [
            'ffmpeg', '-i', caminho_video,
            '-af', 'silencedetect=noise=-40dB:d=0.1',
            '-f', 'null', '-'
        ]
        resultado = subprocess.run(comando_busca, stderr=subprocess.PIPE, text=True)
        stderr_output = resultado.stderr

        # Procura pelo término do primeiro bloco de silêncio
        busca_fim_silencio = re.search(r'silence_end:\s*([\d\.]+)', stderr_output)
        
        if busca_fim_silencio:
            inicio_fala = float(busca_fim_silencio.group(1))
            # Se o silêncio inicial for maior que 0.2 segundos, faz o corte cirúrgico
            if inicio_fala > 0.2:
                print(f"[AUDIO] Cortando {inicio_fala}s de silêncio inicial na Parte {parte_num}")
                video_ajustado = caminho_video.replace('.mp4', '_fala.mp4')
                subprocess.run([
                    'ffmpeg', '-y', '-ss', str(inicio_fala), 
                    '-i', caminho_video, '-c', 'copy', video_ajustado
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(caminho_video)
                os.rename(video_ajustado, caminho_video)
    except Exception as e:
        print(f"[Aviso] Falha ao remover silêncio nativo: {e}")

@app.route('/processar', methods=['POST'])
def processar_cortes():
    try:
        video_url = request.form.get('url')
        quantidade_cortes = int(request.form.get('quantidade', 20))
        tempo_corte = int(request.form.get('tempo', 30))
        texto_topo = request.form.get('texto_topo', '').upper()
        texto_baixo = request.form.get('texto_baixo', '').upper()
        
        imagem_fundo = request.files.get('fundo')
        
        if not video_url or not imagem_fundo:
            return jsonify({"erro": "Faltam dados essenciais"}), 400
            
        bg_path = os.path.join(UPLOAD_FOLDER, 'fundo.png')
        imagem_fundo.save(bg_path)
        
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

        # CONSTRUÇÃO DO FILTRO VISUAL (1:1 + Fundo 9:16 + Escudo Anti-Copyright + Textos)
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

        # Processamento direto mantendo apenas o áudio original limpo do YouTube
        comando_ffmpeg = [
            'ffmpeg', '-y', '-i', video_original, '-i', bg_path,
            '-filter_complex', filtro_video,
            '-map', '[outv]', '-map', '0:a',
            '-f', 'segment', '-segment_time', str(tempo_corte),
            '-c:v', 'libx264', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            os.path.join(UPLOAD_FOLDER, 'corte_%03d.mp4')
        ]
        
        print("[SERVER] Renderizando lote inteligente...")
        subprocess.run(comando_ffmpeg, check=True)
        
        # Pós-processamento: Cortar o silêncio de cada bloco gerado usando FFmpeg nativo
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
      
