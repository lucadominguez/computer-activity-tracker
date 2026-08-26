#!/usr/bin/env python3
"""Interactive X11 target used by manual activity-tracker exercises."""
import os
import tkinter as tk

os.environ.setdefault("DISPLAY", ":100")


def main():
    root = tk.Tk()
    root.title("ATSmoke-NotepadStandin")
    root.geometry("600x400+50+50")
    label = tk.Label(
        root,
        text="computer activity tracker smoke window",
        font=("Helvetica", 16),
    )
    label.pack(pady=40)
    entry = tk.Entry(root, font=("Helvetica", 14))
    entry.pack(pady=20)
    entry.focus_set()
    root.update()

    def print_win_id():
        try:
            print("WINID=" + str(root.winfo_id()), flush=True)
        except Exception:
            pass

    root.after(120, print_win_id)
    root.after(4000, lambda: print("ready", flush=True))
    root.mainloop()


if __name__ == "__main__":
    main()
