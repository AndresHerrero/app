from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, current_user
from auth import auth_bp
from models import db, User, UserUpload, SharedUpload
import os
import easyocr
from gtts import gTTS
from googletrans import Translator
from datetime import datetime
from langdetect import detect

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.init_app(app)
app.register_blueprint(auth_bp)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    uploads = UserUpload.query.filter_by(user_id=current_user.id).order_by(UserUpload.timestamp.desc()).limit(5).all()
    compartidas_conmigo = SharedUpload.query.filter_by(recipient_id=current_user.id).order_by(SharedUpload.timestamp.desc()).limit(5).all()

    if request.method == "POST":
        if "image" not in request.files:
            flash("❌ No se ha subido ninguna imagen")
            return render_template("index.html", uploads=uploads, compartidas=compartidas_conmigo, username=current_user.username)

        image_file = request.files["image"]
        idioma_destino = request.form.get("idioma", "es")

        filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{image_file.filename}"
        saved_path = os.path.join(UPLOAD_FOLDER, filename)
        image_file.save(saved_path)

        reader = easyocr.Reader(['en', 'es', 'fr', 'de', 'it', 'pt'], gpu=False)
        resultado = reader.readtext(saved_path, detail=0)
        texto_extraido = "\n".join(resultado)

        try:
            idioma_origen = detect(texto_extraido)
        except:
            idioma_origen = "es"

        traductor = Translator()
        traduccion = traductor.translate(texto_extraido, dest=idioma_destino).text

        audio_original = os.path.join(UPLOAD_FOLDER, f"{filename}_original.mp3")
        tts_original = gTTS(text=texto_extraido, lang=idioma_origen)
        tts_original.save(audio_original)

        audio_traducido = os.path.join(UPLOAD_FOLDER, f"{filename}_traducido.mp3")
        tts_traducido = gTTS(text=traduccion, lang=idioma_destino)
        tts_traducido.save(audio_traducido)

        texto_path = os.path.join(UPLOAD_FOLDER, f"{filename}_extraido.txt")
        with open(texto_path, "w", encoding="utf-8") as f:
            f.write(texto_extraido)

        upload = UserUpload(
            filename=filename,
            text=texto_extraido,
            user_id=current_user.id
        )
        db.session.add(upload)
        db.session.commit()

        flash("✅ Imagen procesada correctamente")

        idiomas_legibles = {
            "es": "Español", "en": "Inglés", "fr": "Francés",
            "de": "Alemán", "it": "Italiano", "pt": "Portugués"
        }

        idioma_origen_nombre = idiomas_legibles.get(idioma_origen, idioma_origen)
        idioma_destino_nombre = idiomas_legibles.get(idioma_destino, idioma_destino)

        return render_template(
            "resultado.html",
            imagen_nombre=filename,
            texto=texto_extraido,
            traduccion=traduccion,
            texto_path=os.path.basename(texto_path),
            audio_original=os.path.basename(audio_original),
            audio_traducido=os.path.basename(audio_traducido),
            idioma_origen=idioma_origen_nombre,
            idioma_destino=idioma_destino_nombre,
            upload_id=upload.id
        )

    return render_template("index.html", uploads=uploads, compartidas=compartidas_conmigo, username=current_user.username)

@app.route("/procesar", methods=["GET", "POST"])
@login_required
def procesar():
    if request.method == "POST":
        return redirect(url_for("index"), code=307)
    return render_template("procesar.html")

@app.route("/descargar/<nombre_archivo>")
@login_required
def descargar(nombre_archivo):
    return send_file(os.path.join(UPLOAD_FOLDER, nombre_archivo), as_attachment=True)

@app.route("/audio/<nombre_archivo>")
@login_required
def audio(nombre_archivo):
    return send_file(os.path.join(UPLOAD_FOLDER, nombre_archivo), mimetype="audio/mp3")

@app.route("/imagen/<nombre_archivo>")
@login_required
def imagen(nombre_archivo):
    return send_file(os.path.join(UPLOAD_FOLDER, nombre_archivo), mimetype="image/jpeg")

@app.route("/eliminar/<int:upload_id>", methods=["POST"])
@login_required
def eliminar(upload_id):
    upload = UserUpload.query.get_or_404(upload_id)

    if upload.user_id != current_user.id:
        return "No autorizado", 403

    try:
        os.remove(os.path.join(UPLOAD_FOLDER, upload.filename))
        os.remove(os.path.join(UPLOAD_FOLDER, f"{upload.filename}_extraido.txt"))
        os.remove(os.path.join(UPLOAD_FOLDER, f"{upload.filename}_original.mp3"))
        os.remove(os.path.join(UPLOAD_FOLDER, f"{upload.filename}_traducido.mp3"))
    except FileNotFoundError:
        pass

    db.session.delete(upload)
    db.session.commit()
    flash("🗑 Imagen eliminada correctamente")
    return redirect(url_for("index"))

@app.route("/compartir/<int:upload_id>", methods=["POST"])
@login_required
def compartir(upload_id):
    username_dest = request.form.get("destinatario")
    destinatario = User.query.filter_by(username=username_dest).first()

    if not destinatario:
        flash("❌ Usuario no encontrado")
        return redirect(url_for("index"))

    shared = SharedUpload(
        upload_id=upload_id,
        sender_id=current_user.id,
        recipient_id=destinatario.id
    )
    db.session.add(shared)
    db.session.commit()
    flash(f"✅ Imagen compartida con {destinatario.username}")
    return redirect(url_for("index"))

@app.route("/compartido/<int:upload_id>")
@login_required
def resultado_compartido(upload_id):
    registro = SharedUpload.query.filter_by(upload_id=upload_id, recipient_id=current_user.id).first_or_404()
    upload = registro.upload
    base = upload.filename

    return render_template(
        "resultado.html",
        imagen_nombre=base,
        texto=upload.text,
        traduccion=None,
        texto_path=f"{base}_extraido.txt",
        audio_original=f"{base}_original.mp3",
        audio_traducido=f"{base}_traducido.mp3",
        idioma_origen="Detectado",
        idioma_destino="Traducción",
        upload_id=upload.id
    )

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)