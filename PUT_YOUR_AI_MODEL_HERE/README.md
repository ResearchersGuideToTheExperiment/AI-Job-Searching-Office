# Put your local GGUF model here

The easiest setup is to install Ollama and run the download commands in the main README. Ollama then manages the model in its own storage; you do not need to put a file here.

If you already have a compatible Qwen3 8B GGUF:

1. Put the GGUF directly in this folder and name it `model.gguf`.
2. Start Ollama.
3. Open Command Prompt or PowerShell in the **project root**, then run:

```bat
ollama create qwen3-office -f PUT_YOUR_AI_MODEL_HERE\Modelfile
ollama list
```

The bundled `Modelfile` is a small text configuration, not model weights. It points to `./model.gguf` relative to this folder. If you prefer another filename or subfolder, update that path in your local copy, but do not commit machine-specific paths.

The app connects to the installed Ollama model name `qwen3-office`; placing a GGUF here alone does not load it.

Optional private preferences may be placed in `AI_instructions/job_preferences.md` and `AI_instructions/writing_style.md` inside this folder. Templates are in `examples/`.

Only this README and the bundled Modelfile are public. Model weights and personal instructions are ignored by Git and rejected by the release exporter. Model licenses apply separately from the app license.
