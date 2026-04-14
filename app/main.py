import os
import webview
from app.backend.api import TermExtractorAPI


def main():
    api = TermExtractorAPI()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_path = os.path.join(base_dir, 'frontend', 'index.html')

    window = webview.create_window(
        'Term Extractor',
        frontend_path,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1024, 700)
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == '__main__':
    main()
