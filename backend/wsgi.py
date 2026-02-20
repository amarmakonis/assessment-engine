"""WSGI entry point for Gunicorn / production servers."""

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    from app.config import get_settings

    s = get_settings()
    app.run(host=s.FLASK_HOST, port=s.FLASK_PORT, debug=s.DEBUG)
