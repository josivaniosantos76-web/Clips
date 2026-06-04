# -*- coding: utf-8 -*-
import os
import subprocess
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(CORS)  # Permite que o seu site no celular converse com o servidor

UPLOAD_FOLDER = 'workspace'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/processar', methods=['POST'])
def processar_cortes():
    try:
        # 1. Recebe os dados do celular
        video_url = request.form.get('url')
        quantidade_cortes = int(request.form.get('quantidade', 20))
        tempo_corte = int(request.form.get('tempo', 30))
        imagem_fundo = request.files.get('fundo')
        
        if not video_url or not imagem_fundo:
            return jsonify({"erro": "Faltam dados essenciais"}), 400
            
        # 2. Salva a imagem de fundo temporariamente
        bg_path = os.path.join(UPLOAD_FOLDER, 'fundo.png')
        imagem_fundo.save(bg_path)
        
        # 3. Baixa o vídeo do YouTube usando yt-dlp
        video_original = os.path.join(UPLOAD_FOLDER, 'downloaded.mp4')
        print("[SERVER] Baixando do YouTube...")
        subprocess.run([
            'yt-dlp', 
            '-f', 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]', 
            '-o', video_original, 
            video_url
        ], check=True)
        
        # 4. Processa tudo no FFmpeg (A mágica do 1:1 centralizado no 9:16)
        print(f"[SERVER] Renderizando {quantidade_cortes} cortes com o fundo fixo...")
        
        # Limpa cortes anteriores
        for f in os.listdir(UPLOAD_FOLDER):
            if f.startswith('corte_') and f.endswith('.mp4'):
                os.remove(os.path.join(UPLOAD_FOLDER, f))
                
        # Comando FFmpeg em lote para redimensionar o vídeo para 1:1, sobrepor no fundo 9:16 e cortar em partes
        comando_ffmpeg = [
            'ffmpeg', '-i', video_original, '-i', bg_path,
            '-filter_complex', '[0:v]scale=1080:1080,setsar=1[vid]; [1:v]scale=1080:1920[bg]; [bg][vid]overlay=(W-w)/2:(H-h)/2[outv]',
            '-map', '[outv]', '-map', '0:a',
            '-f', 'segment', '-segment_time', str(tempo_corte),
            '-c:v', 'libx264', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            os.path.join(UPLOAD_FOLDER, 'corte_%03d.mp4')
        ]
        
        # Executa o FFmpeg e limita os cortes à quantidade pedida pelo usuário
        subprocess.run(comando_ffmpeg, check=True)
        
        # Lista os arquivos finais gerados
        todos_arquivos = sorted([f for f in os.listdir(UPLOAD_FOLDER) if f.startswith('corte_')])
        arquivos_finais = todos_arquivos[:quantidade_cortes]
        
        return jsonify({"sucesso": True, "videos": arquivos_finais})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    # Roda na porta 5000 pronto para receber comandos externos
    app.run(host='0.0.0.0', port=5000, debug=True)
