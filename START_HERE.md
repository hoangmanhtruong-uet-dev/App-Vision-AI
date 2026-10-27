# Chạy Vision AI hoàn chỉnh

## 1. Cài đặt và chuẩn bị

Dự án đã được phân chia cấu trúc rõ ràng:
- `backend/`: FastAPI server, database (SQLite/PostgreSQL), API và Auth.
- `frontend/`: Ứng dụng PWA (HTML, CSS, JS, YOLO ONNX model, assets).
- `dist/`: Bundle production được tự động tạo khi chạy `npm run build`.
- `scripts/`: Scripts kiểm tra và build.

### Cài đặt dependencies (lần đầu):
```powershell
# Frontend dependencies
npm install

# Backend dependencies (nếu chưa kích hoạt virtualenv)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
```

## 2. Build frontend

Chạy lệnh build để compile và copy assets sang `dist/`:
```powershell
npm run build
```

## 3. Khởi chạy ứng dụng

Từ thư mục gốc dự án:
```powershell
npm run dev
# hoặc chạy trực tiếp bằng python trong backend:
# cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Truy cập:
- Giao diện ứng dụng: <http://127.0.0.1:8000>
- API Docs (Swagger): <http://127.0.0.1:8000/docs>

Trên điện thoại cùng Wi-Fi, mở `http://IP-MAY-TINH:8000`. Camera trên điện thoại chỉ hoạt động khi trang dùng HTTPS; upload ảnh vẫn dùng được qua HTTP nội bộ.

## 17 màn hình

Menu góc trái trong ứng dụng cho phép mở trực tiếp toàn bộ 17 màn UI. Các route dùng dạng `#/scanner`, `#/history`, `#/collections`, `#/settings` và các state tương ứng.
