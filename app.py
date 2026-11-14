import os
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
from backend.main import app as fastapi_app

@spaces.GPU
def zero_gpu_check():
    return "ZeroGPU Active and Running!"

with gr.Blocks() as demo:
    gr.Markdown("## AI Data Analytics Backend Server is Live")
    btn = gr.Button("Verify ZeroGPU Status")
    out = gr.Textbox(label="Status")
    btn.click(fn=zero_gpu_check, outputs=out)

if __name__ == "__main__":
    # 1. Start Gradio via demo.launch so ZeroGPU detects @spaces.GPU properly
    _, local_url, _ = demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        prevent_thread_lock=True
    )
    
    # 2. Attach all FastAPI routes (/api/*, /docs, etc.) directly onto Gradio's running FastAPI server
    for route in fastapi_app.routes:
        demo.server_app.routes.insert(0, route)
        
    # Copy CORS and middleware from FastAPI app if present
    demo.server_app.user_middleware = fastapi_app.user_middleware
    demo.server_app.middleware_stack = demo.server_app.build_middleware_stack()
    
    print("FastAPI routes successfully mounted onto Gradio ZeroGPU server on port 7860!")
    demo.block_thread()