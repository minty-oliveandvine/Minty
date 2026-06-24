from pettycash import create_app

app = create_app()


if __name__ == "__main__":
    debug_mode = __import__("os").environ.get("FLASK_DEBUG", "False") == "True"
    app.run(debug=debug_mode, host="0.0.0.0", port=5001)
