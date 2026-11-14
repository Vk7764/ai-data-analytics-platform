import huggingface_hub
if not hasattr(huggingface_hub, "HfFolder"):
    class _DummyHfFolder:
        @classmethod
        def get_token(cls): return None
        @classmethod
        def save_token(cls, token): pass
    huggingface_hub.HfFolder = _DummyHfFolder

import spaces
import gradio as gr
import uvicorn
from backend.main import app

@spaces.GPU
def zero_gpu_check():
    return "ZeroGPU Active"

with gr.Blocks() as demo:
    gr.Markdown("### AI Data Analytics Backend API is Running")
    btn = gr.Button("Check GPU Status")
    out = gr.Textbox()
    btn.click(fn=zero_gpu_check, outputs=out)

# Mount Gradio on '/gradio' so all FastAPI routes (/, /docs, /api/*) work directly
app = gr.mount_gradio_app(app, demo, path="/gradio")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)