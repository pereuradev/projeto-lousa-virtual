"""Ponto de entrada: python main.py."""
import logging
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).parent / ".cache" / "matplotlib"))
        from lousa.app import main
        raise SystemExit(main())
    except Exception as exc:
        # O log contém erros, nunca frames de câmera.
        logging.basicConfig(filename=Path(__file__).with_name("erro.log"), encoding="utf-8", level=logging.ERROR)
        logging.exception("Erro ao executar a lousa")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Projeto Lousa Virtual", f"Não foi possível iniciar:\n{exc}\n\nExecute Instalar ou reparar.cmd.\nDetalhes em erro.log.")
            root.destroy()
        except Exception:
            print(f"Não foi possível iniciar: {exc}. Execute Instalar ou reparar.cmd.", file=sys.stderr)
        raise SystemExit(1)
