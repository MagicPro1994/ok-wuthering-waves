"""Train the sailing obstacle detector (land, rock, structure, shallows) and export it to ONNX.

Run it with the separate training environment, not the bot's own .venv:

    .tmp\\train-venv\\Scripts\\python.exe tools\\train_sail_yolo.py [--epochs 150] [--device 0]

Everything it downloads or writes (weights, caches, runs) stays under .tmp/ in the project.
The dataset is .tmp/sail_yolo/ (images/, labels/, data.yaml), see docs for how it is labelled.
"""
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / '.tmp'

# keep every cache inside the project
os.environ.setdefault('TORCH_HOME', str(TMP / 'cache' / 'torch'))
os.environ.setdefault('YOLO_CONFIG_DIR', str(TMP / 'cache' / 'ultralytics'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default=str(TMP / 'sail_yolo' / 'data.yaml'))
    parser.add_argument('--base', default='yolov8n.pt', help='starting weights')
    parser.add_argument('--epochs', type=int, default=150)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--device', default='0', help="'0' for the GPU, 'cpu' otherwise")
    parser.add_argument('--name', default='sail')
    args = parser.parse_args()

    from ultralytics import YOLO

    os.chdir(TMP / 'cache')      # ultralytics downloads the base weights into the working directory
    model = YOLO(args.base)
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device,
        workers=0,               # Windows: no data loader worker processes
        amp=False,               # the AMP check downloads another model and is unreliable on ROCm
        patience=40, project=str(TMP / 'runs'), name=args.name, exist_ok=True,
        fliplr=0.5, flipud=0.0, degrees=0.0, mosaic=1.0, hsv_h=0.015, hsv_s=0.6, hsv_v=0.5,
        plots=True,
    )
    best = TMP / 'runs' / args.name / 'weights' / 'best.pt'
    exported = YOLO(str(best)).export(format='onnx', imgsz=args.imgsz, opset=12, simplify=False)
    target = TMP / 'runs' / args.name / 'sail.onnx'
    shutil.copy(exported, target)
    print(f'exported {target}')


if __name__ == '__main__':
    main()
