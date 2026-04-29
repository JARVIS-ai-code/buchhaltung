#!/usr/bin/env python3
import os
import sys


def main() -> None:
    if os.name == "nt":
        from app_qt import main as qt_main

        qt_main()
        return

    from app_gtk import main as gtk_main

    gtk_main()


if __name__ == "__main__":
    main()
