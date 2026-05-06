import uvicorn

from src.hf_download.run import run
from src.config.hf_download.config import DownloadConfig
from src.config import paths

if __name__ == "__main__":
    # uvicorn.run("src.webui.app:app", host="127.0.0.1", port=8080, reload=True)
    run(DownloadConfig.from_yaml(str(paths.hf_download_yaml)))
    print("Downloaded model")