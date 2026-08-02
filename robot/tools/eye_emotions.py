import time

from display.eye_controller import Animation, EyeController


def _print_menu(items: list[tuple[str, Animation]]) -> None:
    print("\n=== Eye Emotion Test Menu ===")
    for i, (name, _anim) in enumerate(items, start=1):
        print(f"{i:2d}) {name}")
    print(" a) Play all (loop)")
    print(" q) Quit")


def main() -> None:
    eyes = EyeController()

    items: list[tuple[str, Animation]] = [
        ("RESET", Animation.RESET),
        ("HAPPY", Animation.HAPPY),
        ("SLEEP", Animation.SLEEP),
        ("SACCADE_RANDOM", Animation.SACCADE_RANDOM),
        ("MOVE_LEFT_BIG", Animation.MOVE_LEFT_BIG),
        ("MOVE_RIGHT_BIG", Animation.MOVE_RIGHT_BIG),
        ("BLINK_SHORT", Animation.BLINK_SHORT),
        ("BLINK_LONG", Animation.BLINK_LONG),
        ("CURIOUS", Animation.CURIOUS),
        ("CONFUSED", Animation.CONFUSED),
        ("THINKING", Animation.THINKING),
        ("IMPATIENT", Animation.IMPATIENT),
    ]

    try:
        while True:
            _print_menu(items)
            choice = input("Select: ").strip().lower()

            if choice in ("q", "quit", "exit"):
                break

            if choice in ("a", "all"):
                print("Playing all (Ctrl+C to stop)...")
                try:
                    while True:
                        for name, anim in items:
                            print(f"Playing: {name}")
                            eyes.play(anim)
                            time.sleep(2.0)
                except KeyboardInterrupt:
                    continue

            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(items):
                    name, anim = items[idx - 1]
                    print(f"Playing: {name}")
                    eyes.play(anim)
                else:
                    print("Invalid number.")
                continue

            print("Invalid choice.")
    finally:
        try:
            eyes.reset()
        except Exception:
            pass


if __name__ == "__main__":
    main()
