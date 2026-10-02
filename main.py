import os

from pettycash import create_app
from services.app_runtime.env import is_development

app = create_app()


if __name__ == "__main__":
    app.run(debug=is_development(), host="0.0.0.0", port=int(os.environ.get("PORT", 8010)))
