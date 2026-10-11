"""Keep the last image and stop reason visible after the worker finishes."""

import queue


_root = None


def explain_stop(reason):
    if "Time limit" in reason or "time limit" in reason:
        return "Tidsgränsen nåddes. Starta ett nytt försök för att fortsätta."
    if "aspect ratio" in reason or "size changed" in reason:
        return "Spelfönstrets format ändrades. Återställ proportionerna eller kalibrera om."
    if "Expected one cube" in reason or "Cube lost" in reason:
        return "Kuben försvann eller kunde inte kännas igen. Starta om banan och gör ett nytt försök."
    if "Unsupported" in reason:
        return "Ett hinder eller spelläge saknar stöd. Den här versionen stöder platt mark och spikar."
    if "focus" in reason:
        return "Geometry Dash tappade fokus. Starta ett nytt försök och återgå till spelet."
    if "F9" in reason:
        return "Stoppad med F9. Hoppknappen har släppts."
    if "STOP" in reason:
        return "Stoppad med STOP. Hoppknappen har släppts."
    if "Ground line" in reason:
        return "Marken syns inte. Kontrollera att en bana spelas och att bilden är rätt kalibrerad."
    return "Styrningen är stoppad. Läs orsaken nedan innan du startar igen."


def session_window(*, title, updates, finished, on_stop, on_arm, result,
                   report_path, retry=True):
    global _root
    import tkinter as tk
    from PIL import Image, ImageTk

    # Keep one Tcl interpreter across retries. Recreating Tk while capture
    # threads run lets Python GC delete an old interpreter on the wrong thread.
    if _root is None:
        _root = tk.Tk()
    root = _root
    root.deiconify()
    root.title(title)
    root.geometry("720x600+10+50")
    root.minsize(540, 430)
    banner = tk.Label(root, text="Välj Geometry Dash. F8 startar styrning, F9 stoppar.",
                      bg="#18382c", fg="white", wraplength=680, padx=12, pady=10)
    banner.pack(fill="x")
    label = tk.Label(root, text="Väntar på spelbild…", bg="#101418", fg="white")
    label.pack(fill="both", expand=True)
    detail = tk.Label(root, text="", justify="left", anchor="w", wraplength=680, padx=12, pady=8)
    detail.pack(fill="x")
    controls = tk.Frame(root)
    controls.pack(fill="x", padx=8, pady=8)
    wants_restart = False
    shown = False
    scheduled = set()

    def later(delay, callback):
        handle = None
        def invoke():
            scheduled.discard(handle)
            callback()
        handle = root.after(delay, invoke)
        scheduled.add(handle)

    def destroy_window(*, keep_root=False):
        global _root
        for handle in scheduled:
            root.after_cancel(handle)
        scheduled.clear()
        # Destroy PhotoImage on the UI thread before releasing its widgets.
        label.configure(image="")
        label.image = None
        for widget in root.winfo_children():
            widget.destroy()
        root.quit()
        if keep_root:
            root.withdraw()
        else:
            root.destroy()
            _root = None

    def request_close():
        if not finished.is_set():
            on_stop()
            later(50, close_when_finished)
        else:
            destroy_window()

    def close_when_finished():
        if finished.is_set():
            destroy_window()
        else:
            later(50, close_when_finished)

    def restart():
        nonlocal wants_restart
        if finished.is_set():
            wants_restart = True
            destroy_window(keep_root=True)

    arm_button = None
    if on_arm:
        arm_button = tk.Button(controls, text="Aktivera om 3 s / F8", command=lambda: later(3000, on_arm))
        arm_button.pack(side="left", padx=3)
    retry_button = tk.Button(controls, text="Nytt försök", state="disabled", command=restart)
    if retry:
        retry_button.pack(side="left", padx=3)
    stop_button = tk.Button(controls, text="STOP / F9", bg="#bf263f", fg="white", command=on_stop)
    stop_button.pack(side="right", padx=3)
    tk.Button(controls, text="Stäng", command=request_close).pack(side="right", padx=3)
    root.protocol("WM_DELETE_WINDOW", request_close)

    def refresh():
        nonlocal shown
        try:
            frame = updates.get_nowait()
            if isinstance(frame, str):
                banner.configure(text=frame)
            else:
                preview = Image.fromarray(frame)
                preview.thumbnail((max(480, root.winfo_width()-20), 400))
                label.image = ImageTk.PhotoImage(preview)
                label.configure(image=label.image, text="")
        except queue.Empty:
            pass
        if finished.is_set() and not shown:
            shown = True
            reason = str(result.get("stop_reason") or "Session ended")
            banner.configure(text="STOPPAD · " + explain_stop(reason), bg="#63293a")
            detail.configure(text=f"Orsak: {reason}\nGiltiga bilder: {result.get('valid_frames', 0)} / "
                                  f"{result.get('frames', 0)} · Hopptryck: {result.get('presses', 0)}\n"
                                  f"Rapport: {report_path}")
            stop_button.configure(state="disabled")
            if arm_button:
                arm_button.configure(state="disabled")
            retry_button.configure(state="normal")
        later(50, refresh)

    later(50, refresh)
    try:
        root.mainloop()
    finally:
        if not finished.is_set():
            on_stop()
    return wants_restart
