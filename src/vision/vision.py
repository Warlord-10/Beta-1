import os

import cactus


def describe_image(image_path:str):
    try:
        vision = cactus.Mirage()
        result = vision.describe(os.path.expanduser(image_path), language="en")
        return result
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    print(describe_image("~/Desktop/bank/WhatsApp Image 2026-04-27 at 09.29.50.jpeg"))