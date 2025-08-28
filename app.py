import os
import uuid
from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, send_from_directory, abort, current_app
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from processing import extract_first_frame, run_tracking


# ---------- App factory ----------
def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev_key_change_me')

    # Folders (ephemeral on Render Free)
    app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
    app.config['TMP_FOLDER']     = os.getenv('TMP_FOLDER', 'static/tmp')
    app.config['RESULT_FOLDER']  = os.getenv('RESULT_FOLDER', 'static/results')

    for p in (app.config['UPLOAD_FOLDER'], app.config['TMP_FOLDER'], app.config['RESULT_FOLDER']):
        os.makedirs(p, exist_ok=True)

    # ---------- Routes ----------
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.post('/upload')
    def upload():
        if 'video' not in request.files:
            return redirect(url_for('index'))
        f = request.files['video']
        if f.filename == '':
            return redirect(url_for('index'))

        job_id = str(uuid.uuid4())[:8]
        fname = secure_filename(f.filename)
        # ensure mp4 extension for writer compatibility
        base, ext = os.path.splitext(fname)
        if ext.lower() not in ['.mp4', '.mov', '.avi', '.mkv']:
            ext = '.mp4'
        video_name = base + ext

        video_dir = os.path.join(app.config['UPLOAD_FOLDER'], job_id)
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, video_name)
        f.save(video_path)

        # Extract first frame to PNG for browser annotation
        png_path = extract_first_frame(video_path, app.config['TMP_FOLDER'], job_id)
        if png_path is None:
            abort(400, description='Could not read video first frame.')

        return redirect(url_for('annotate', job_id=job_id))

    @app.get('/annotate/<job_id>')
    def annotate(job_id):
        # first-frame image URL
        img_url = url_for('first_frame', job_id=job_id)
        return render_template('annotate.html', job_id=job_id, img_url=img_url)

    @app.get('/first_frame/<job_id>')
    def first_frame(job_id):
        # serve the first-frame PNG from static/tmp/<job_id>_first.png
        tmp_file = f'{job_id}_first.png'
        tmp_path = os.path.join(app.config['TMP_FOLDER'], tmp_file)
        if not os.path.exists(tmp_path):
            abort(404)
        return send_from_directory(app.config['TMP_FOLDER'], tmp_file)

    @app.post('/process')
    def process():
        try:
            data = request.get_json(force=True)
            job_id = data.get('job_id')
            scale_cm = float(data.get('scale_cm', 0))
            p1 = data.get('p1')  # {x, y}
            p2 = data.get('p2')
            bbox = data.get('bbox')  # {x, y, w, h}

            if not (job_id and scale_cm > 0 and p1 and p2 and bbox):
                abort(400, description='Missing parameters.')

            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], job_id)
            if not os.path.isdir(upload_dir):
                abort(404, description='Job not found.')

            # find the video in upload_dir (only one expected)
            video_files = [f for f in os.listdir(upload_dir)
                           if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv'))]
            if not video_files:
                abort(404, description='Video not found.')
            video_path = os.path.join(upload_dir, video_files[0])

            result_dir = os.path.join(app.config['RESULT_FOLDER'], job_id)
            os.makedirs(result_dir, exist_ok=True)

            out_video, out_csv = run_tracking(
                video_path=video_path,
                result_dir=result_dir,
                scale_cm=scale_cm,
                p1=p1, p2=p2,
                bbox=bbox
            )

            return jsonify({
                'ok': True,
                'video_url': url_for('download_result', job_id=job_id, filename=os.path.basename(out_video)),
                'csv_url':   url_for('download_result', job_id=job_id, filename=os.path.basename(out_csv))
            })
        except Exception as e:
            current_app.logger.exception(e)
            return jsonify({'ok': False, 'error': str(e)}), 400

    @app.get('/results/<job_id>/<path:filename>')
    def download_result(job_id, filename):
        result_dir = os.path.join(app.config['RESULT_FOLDER'], job_id)
        if not os.path.isdir(result_dir):
            abort(404)
        return send_from_directory(result_dir, filename, as_attachment=True)

    return app


# For Render Procfile / flask run
app = create_app()
