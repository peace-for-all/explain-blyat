"""Terminal input only; no model calls or invented answers."""


def read_answer(question: str, index: int, total: int) -> str | None:
    print(f"\nВопрос {index}/{total}: {question}", flush=True)
    print("Введите ответ; пустая строка завершает ответ. Сразу Enter — пропустить. Ctrl-C — отменить.", flush=True)
    lines = []
    while True:
        try:
            line = input("> " if not lines else "… ")
        except EOFError:
            raise RuntimeError("Input closed during questions; cancelled before rewriting. Completed answers were saved.") from None
        if not line.strip():
            return "\n".join(lines) if lines else None
        lines.append(line)
