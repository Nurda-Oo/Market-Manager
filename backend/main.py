import sqlite3
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Market-Manager")
DB = "market.db"


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES sales(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)

init_db()


class ProductIn(BaseModel):
    barcode: str
    name: str
    price: float
    stock: int = 0

class SaleItemIn(BaseModel):
    product_id: int
    quantity: int = 1

class SaleIn(BaseModel):
    items: List[SaleItemIn]

# ------ Products --------
@app.post("/products")
def add_product(p: ProductIn):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO products (barcode, name, price, stock) VALUES (?, ?, ?, ?)",
                (p.barcode, p.name, p.price, p.stock),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Товар с таким штрихкодом уже есть")
    return {"message": "Товар добавлен"}


@app.get("/products")
def list_products():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products").fetchall()
    return [dict(r) for r in rows]


@app.get("/products/{barcode}")
def get_product(barcode: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE barcode = ?", (barcode,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return dict(row)

#------ Sales --------
@app.post("/sales")
def create_sale(sale: SaleIn):
    if not sale.items:
        raise HTTPException(status_code=400, detail="Чек пустой")

    # объединяем одинаковые штрихкоды в одну позицию
    wanted = {}
    for item in sale.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Количество должно быть больше нуля")
        wanted[item.barcode] = wanted.get(item.barcode, 0) + item.quantity

    with get_conn() as conn:
        lines = []
        total = 0
        for barcode, qty in wanted.items():
            product = conn.execute("SELECT * FROM products WHERE barcode = ?", (barcode,)).fetchone()
            if product is None:
                raise HTTPException(status_code=404, detail=f"Товар с {barcode} не найден")
            if product["stock"] < qty:
                raise HTTPException(status_code=400, detail=f"Недостаточно товара {product['name']} на складе")
            lines.append((product["id"], qty, product["price"]))
            total += product["price"] * qty

        cur = conn.execute("INSERT INTO sales (total) VALUES (?)", (total,))
        sale_id = cur.lastrowid

        result_items = []
        for product, qty in lines:
            conn.execute(
                "INSERT INTO sale_items (sale_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                (sale_id, product, qty, product["price"]),
            )
            conn.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?", (qty, product)
            )
            result_items.append({"product_id": product, "quantity": qty})   

    return {"sale_id": sale_id, "total": total, "items": result_items}

@app.get("/sales")
def list_sales():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM sales ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]

@app.get("/sales/{sale_id}")
def get_sale(sale_id: int):
    with get_conn() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        if sale is None:
            raise HTTPException(status_code=404, detail="Чек не найден")
        items = conn.execute(
            "SELECT si.*, p.barcode, p.name FROM sale_items si JOIN products p ON si.product_id = p.id WHERE si.sale_id = ?",
            (sale_id,),
        ).fetchall()
    return {"sale": dict(sale), "items": [dict(i) for i in items]}