from sqlalchemy import select, text
from app.core.database import async_session, engine, Base
from app.core.security import hash_password

from app.models.table import Table
from app.models.product import Product
from app.models.category import Category
from app.models.user import User
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.supplier import Supplier
from app.models.stock_history import StockHistory
from app.models.promotion import Promotion
from app.models.setting import Setting
from app.models.employee import Employee
from app.models.daily_payment import DailyPayment
from app.models.expense import Expense
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.customer import Customer
from app.models.notification import Notification
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment


SEED_TABLES = [
    {"number": 1, "status": "vazia", "is_balcao": False},
    {"number": 2, "status": "vazia", "is_balcao": False},
    {"number": 3, "status": "vazia", "is_balcao": False},
    {"number": 4, "status": "vazia", "is_balcao": False},
    {"number": 5, "status": "vazia", "is_balcao": False},
    {"number": 6, "status": "vazia", "is_balcao": False},
    {"number": 7, "status": "vazia", "is_balcao": False},
    {"number": 8, "status": "vazia", "is_balcao": False},
    {"number": 9, "status": "vazia", "is_balcao": False},
    {"number": 10, "status": "vazia", "is_balcao": False},
    {"number": 0, "status": "vazia", "is_balcao": True},
]

SEED_PRODUCTS = [
    # --- CERVEJAS GARRAFAS 600ML (Alto Giro) ---
    {"name": "AMSTEL GF 600ML RETORNAVEL", "category": "Cervejas Garrafas 600ml", "price": 10.0, "cost": 6.0, "stock": 144, "min_stock": 48},
    {"name": "HEINEKEN GF 600ML RETORNAVEL", "category": "Cervejas Garrafas 600ml", "price": 14.0, "cost": 8.8, "stock": 192, "min_stock": 48},
    {"name": "ORIGINAL GF 600ML RETORNAVEL", "category": "Cervejas Garrafas 600ml", "price": 12.0, "cost": 7.5, "stock": 144, "min_stock": 48},
    {"name": "SPATEN GF 600ML RETORNAVEL", "category": "Cervejas Garrafas 600ml", "price": 12.0, "cost": 7.5, "stock": 120, "min_stock": 48},
    {"name": "STELLA ARTOIS GF 600ML RETONAVEL", "category": "Cervejas Garrafas 600ml", "price": 13.0, "cost": 8.2, "stock": 72, "min_stock": 24},
    
    # --- CERVEJAS LATAS (Alto Giro) ---
    {"name": "AMSTEL LT 473ML", "category": "Cervejas Latas", "price": 7.0, "cost": 4.2, "stock": 120, "min_stock": 36},
    {"name": "BRAHMA CHOPP LT 473ML", "category": "Cervejas Latas", "price": 7.0, "cost": 4.2, "stock": 120, "min_stock": 36},
    {"name": "BRAHMA DM LT 350ML", "category": "Cervejas Latas", "price": 6.0, "cost": 3.5, "stock": 120, "min_stock": 36},
    {"name": "BUDWEISER LT 473ML", "category": "Cervejas Latas", "price": 7.0, "cost": 4.2, "stock": 120, "min_stock": 36},
    {"name": "CORONA LT 473ML", "category": "Cervejas Latas", "price": 10.0, "cost": 6.5, "stock": 72, "min_stock": 24},
    {"name": "HEINEKEN LT 473ML", "category": "Cervejas Latas", "price": 8.0, "cost": 5.0, "stock": 144, "min_stock": 48},
    {"name": "LAGUNITAS LT 350ML", "category": "Cervejas Latas", "price": 10.0, "cost": 6.5, "stock": 48, "min_stock": 12},
    {"name": "ORIGINAL LT 473ML", "category": "Cervejas Latas", "price": 7.0, "cost": 4.2, "stock": 120, "min_stock": 36},
    {"name": "SPATEN LT 473ML", "category": "Cervejas Latas", "price": 7.0, "cost": 4.2, "stock": 120, "min_stock": 36},
    
    # --- CERVEJAS LONGNECKS (Giro Médio/Alto) ---
    {"name": "BUDWEISER LN 330ML", "category": "Cervejas Longnecks", "price": 9.0, "cost": 5.5, "stock": 72, "min_stock": 24},
    {"name": "CORONA LN 330ML", "category": "Cervejas Longnecks", "price": 10.0, "cost": 6.0, "stock": 72, "min_stock": 24},
    {"name": "CORONA CERO LN 330ML", "category": "Cervejas Longnecks", "price": 10.0, "cost": 6.0, "stock": 36, "min_stock": 12},
    {"name": "HEINEKEN LN 330ML", "category": "Cervejas Longnecks", "price": 10.0, "cost": 6.0, "stock": 96, "min_stock": 24},
    {"name": "SKOL BEATS SENSES/GT LONGNECK", "category": "Cervejas Longnecks", "price": 12.0, "cost": 7.0, "stock": 48, "min_stock": 12},
    {"name": "STELLA ARTOIS PURE GOLD LN 330ML", "category": "Cervejas Longnecks", "price": 10.0, "cost": 6.0, "stock": 48, "min_stock": 12},
    {"name": "WEMIX SABORES", "category": "Cervejas Longnecks", "price": 10.0, "cost": 5.5, "stock": 48, "min_stock": 12},
    
    # --- CERVEJAS LITRINHO (Giro Médio) ---
    {"name": "BRAHMA CHOPP LITRINHO 300ML", "category": "Cervejas Litrinho 300ml", "price": 5.0, "cost": 2.8, "stock": 92, "min_stock": 23},
    {"name": "ORIGINAL LITRINHO 300ML", "category": "Cervejas Litrinho 300ml", "price": 5.0, "cost": 2.8, "stock": 92, "min_stock": 23},
    
    # --- WHISKIES (Baixo Giro, Alto Valor) ---
    {"name": "CAVALO BRANCO 1L", "category": "Whiskies", "price": 110.0, "cost": 65.0, "stock": 8, "min_stock": 2},
    {"name": "RED LABEL 1L", "category": "Whiskies", "price": 120.0, "cost": 75.0, "stock": 10, "min_stock": 3},
    {"name": "BLACK LABEL 1L", "category": "Whiskies", "price": 180.0, "cost": 115.0, "stock": 5, "min_stock": 2},
    {"name": "JACK DANIELS N07", "category": "Whiskies", "price": 200.0, "cost": 130.0, "stock": 6, "min_stock": 2},
    {"name": "JACK DANIELS APPLE", "category": "Whiskies", "price": 200.0, "cost": 130.0, "stock": 6, "min_stock": 2},
    {"name": "JACK DANIELS HONEY", "category": "Whiskies", "price": 200.0, "cost": 130.0, "stock": 4, "min_stock": 1},
    {"name": "JACK DANIELS FIRE", "category": "Whiskies", "price": 200.0, "cost": 130.0, "stock": 3, "min_stock": 1},
    {"name": "JACK DANIELS GENTLEMAN", "category": "Whiskies", "price": 280.0, "cost": 180.0, "stock": 3, "min_stock": 1},
    {"name": "JACK DANIELS SELECT BARREL", "category": "Whiskies", "price": 340.0, "cost": 220.0, "stock": 2, "min_stock": 1},
    {"name": "OLD PAR", "category": "Whiskies", "price": 240.0, "cost": 150.0, "stock": 4, "min_stock": 1},
    {"name": "BALLANTINES", "category": "Whiskies", "price": 110.0, "cost": 65.0, "stock": 6, "min_stock": 2},
    {"name": "BUFFALO TRACE", "category": "Whiskies", "price": 240.0, "cost": 150.0, "stock": 2, "min_stock": 1},
    {"name": "BUCHANANS", "category": "Whiskies", "price": 260.0, "cost": 160.0, "stock": 3, "min_stock": 1},
    
    # --- GIN, VODKA, RUM E BITTER (Giro Médio/Baixo) ---
    {"name": "BOMBAY SAPHIRE", "category": "Gin, Vodkas, Rum e Bitter", "price": 140.0, "cost": 90.0, "stock": 4, "min_stock": 1},
    {"name": "BEEFEATER LONDON", "category": "Gin, Vodkas, Rum e Bitter", "price": 120.0, "cost": 75.0, "stock": 5, "min_stock": 2},
    {"name": "TANQUERAY LONDON", "category": "Gin, Vodkas, Rum e Bitter", "price": 140.0, "cost": 90.0, "stock": 6, "min_stock": 2},
    {"name": "ABSOLUT RASPBERRY", "category": "Gin, Vodkas, Rum e Bitter", "price": 120.0, "cost": 75.0, "stock": 4, "min_stock": 1},
    {"name": "SMIRNOFF", "category": "Gin, Vodkas, Rum e Bitter", "price": 60.0, "cost": 35.0, "stock": 12, "min_stock": 4},
    {"name": "CIROC", "category": "Gin, Vodkas, Rum e Bitter", "price": 200.0, "cost": 130.0, "stock": 3, "min_stock": 1},
    {"name": "GREY GOOSE", "category": "Gin, Vodkas, Rum e Bitter", "price": 240.0, "cost": 150.0, "stock": 2, "min_stock": 1},
    {"name": "CAMPARI 1L", "category": "Gin, Vodkas, Rum e Bitter", "price": 85.0, "cost": 50.0, "stock": 8, "min_stock": 3},
    {"name": "DON LUIZ", "category": "Gin, Vodkas, Rum e Bitter", "price": 90.0, "cost": 55.0, "stock": 4, "min_stock": 1},
    {"name": "MALIBU", "category": "Gin, Vodkas, Rum e Bitter", "price": 90.0, "cost": 55.0, "stock": 3, "min_stock": 1},
    {"name": "GENGIBRE GARRAFA 1L", "category": "Gin, Vodkas, Rum e Bitter", "price": 60.0, "cost": 30.0, "stock": 10, "min_stock": 3},
    
    # --- COPÃO E DOSES (Estoque virtual / Copos disponíveis) ---
    {"name": "CAMPARI DOSE", "category": "Copão e Doses", "price": 20.0, "cost": 4.0, "stock": 100, "min_stock": 20},
    {"name": "COPÃO DE RED LABEL OU CAVALO BRANCO COM RED BULL E GELO SABORIZADO", "category": "Copão e Doses", "price": 35.0, "cost": 12.0, "stock": 100, "min_stock": 20},
    {"name": "CAVALO BRANCO DOSE", "category": "Copão e Doses", "price": 20.0, "cost": 5.0, "stock": 100, "min_stock": 20},
    {"name": "RED LABEL DOSE", "category": "Copão e Doses", "price": 20.0, "cost": 6.0, "stock": 100, "min_stock": 20},
    {"name": "CACHAÇAS E BATIDAS DOSE COPO PEQUENO", "category": "Copão e Doses", "price": 5.0, "cost": 1.5, "stock": 100, "min_stock": 20},
    {"name": "GENGIBRE DOSE 1/2 COPO AMERICANO", "category": "Copão e Doses", "price": 7.0, "cost": 2.0, "stock": 100, "min_stock": 20},
    
    # --- SALGADINHOS (Giro Médio) ---
    {"name": "CHEETOS LUA 160G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 20, "min_stock": 5},
    {"name": "CHEETOS ONDA 160G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 20, "min_stock": 5},
    {"name": "DORITOS 120G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 25, "min_stock": 8},
    {"name": "FANDANGOS PRESUNTO 160G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 15, "min_stock": 5},
    {"name": "FANDANGOS QUEIJO 160G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 15, "min_stock": 5},
    {"name": "RUFFLES 115G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 25, "min_stock": 8},
    {"name": "BACONZITOS 86G", "category": "Salgadinhos", "price": 18.0, "cost": 10.0, "stock": 15, "min_stock": 5},
    
    # --- ESPETINHOS (Giro Rápido) ---
    {"name": "BOI", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 40, "min_stock": 15},
    {"name": "FRANGO", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 30, "min_stock": 10},
    {"name": "CORAÇÃO", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 30, "min_stock": 10},
    {"name": "PÃO DE ALHO", "category": "Espetinhos", "price": 15.0, "cost": 6.5, "stock": 30, "min_stock": 10},
    {"name": "MEDALHÃO", "category": "Espetinhos", "price": 14.0, "cost": 6.0, "stock": 25, "min_stock": 8},
    {"name": "QUEIJO COALHO", "category": "Espetinhos", "price": 14.0, "cost": 6.0, "stock": 25, "min_stock": 8},
    {"name": "CARNE DE SOL", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 20, "min_stock": 5},
    {"name": "KAFTA RECHEADA", "category": "Espetinhos", "price": 14.0, "cost": 6.0, "stock": 15, "min_stock": 5},
    {"name": "COSTELA", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 15, "min_stock": 5},
    {"name": "PICANHA SUINA", "category": "Espetinhos", "price": 14.0, "cost": 6.0, "stock": 15, "min_stock": 5},
    {"name": "ASA", "category": "Espetinhos", "price": 12.0, "cost": 5.0, "stock": 10, "min_stock": 3},
    {"name": "CARNEIRO", "category": "Espetinhos", "price": 14.0, "cost": 6.0, "stock": 10, "min_stock": 3},
    
    # --- CARVÃO E GELO (Giro Rápido / Essencial) ---
    {"name": "CARVÃO 4KG", "category": "Carvão e Gelo", "price": 20.0, "cost": 10.0, "stock": 30, "min_stock": 10},
    {"name": "GELO 4KG CUBO", "category": "Carvão e Gelo", "price": 15.0, "cost": 6.0, "stock": 50, "min_stock": 15},
    {"name": "GELO 4KG ESCAMA", "category": "Carvão e Gelo", "price": 15.0, "cost": 6.0, "stock": 30, "min_stock": 10},
    {"name": "GELO SABORIZADO", "category": "Carvão e Gelo", "price": 5.0, "cost": 2.0, "stock": 60, "min_stock": 20},
    
    # --- ÁGUA, REFRIGERANTES E ENERGÉTICOS (Giro Rápido) ---
    {"name": "AGUA MINERAL 500ML", "category": "Água, Refrigerantes e Energéticos", "price": 5.0, "cost": 1.5, "stock": 80, "min_stock": 24},
    {"name": "AGUA CM GÁS 500ML", "category": "Água, Refrigerantes e Energéticos", "price": 5.0, "cost": 1.5, "stock": 40, "min_stock": 12},
    {"name": "COCA COLA LATA 350ML", "category": "Água, Refrigerantes e Energéticos", "price": 8.0, "cost": 3.5, "stock": 96, "min_stock": 24},
    {"name": "COCA COLA 2L", "category": "Água, Refrigerantes e Energéticos", "price": 15.0, "cost": 7.5, "stock": 30, "min_stock": 10},
    {"name": "H2O", "category": "Água, Refrigerantes e Energéticos", "price": 10.0, "cost": 4.5, "stock": 36, "min_stock": 12},
    {"name": "GUARANÁ LATA 350ML", "category": "Água, Refrigerantes e Energéticos", "price": 8.0, "cost": 3.5, "stock": 60, "min_stock": 12},
    {"name": "GUARANÁ 2L", "category": "Água, Refrigerantes e Energéticos", "price": 15.0, "cost": 7.5, "stock": 20, "min_stock": 6},
    {"name": "PINKMOON 600ML", "category": "Água, Refrigerantes e Energéticos", "price": 15.0, "cost": 7.0, "stock": 24, "min_stock": 6},
    {"name": "RED BULL LT 350ML", "category": "Água, Refrigerantes e Energéticos", "price": 15.0, "cost": 8.0, "stock": 96, "min_stock": 24},
]

SEED_PACK_PRODUCTS = [
    # O "stock" aqui representa a quantidade de CAIXAS/ENGRADADOS FECHADOS disponíveis.
    {"name": "CX AMSTEL GF 600ML RETORNAVEL", "category": "Engradados", "price": 240.0, "cost": 144.0, "stock": 15, "min_stock": 5, "pack_size": 24, "pack_unit_product_name": "AMSTEL GF 600ML RETORNAVEL"},
    {"name": "CX HEINEKEN GF 600ML RETORNAVEL", "category": "Engradados", "price": 336.0, "cost": 211.2, "stock": 20, "min_stock": 5, "pack_size": 24, "pack_unit_product_name": "HEINEKEN GF 600ML RETORNAVEL"},
    {"name": "CX ORIGINAL GF 600ML RETORNAVEL", "category": "Engradados", "price": 264.0, "cost": 180.0, "stock": 15, "min_stock": 5, "pack_size": 24, "pack_unit_product_name": "ORIGINAL GF 600ML RETORNAVEL"},
    {"name": "CX SPATEN GF 600ML RETORNAVEL", "category": "Engradados", "price": 264.0, "cost": 180.0, "stock": 15, "min_stock": 5, "pack_size": 24, "pack_unit_product_name": "SPATEN GF 600ML RETORNAVEL"},
    {"name": "CX STELLA ARTOIS GF 600ML RETONAVEL", "category": "Engradados", "price": 312.0, "cost": 196.8, "stock": 10, "min_stock": 3, "pack_size": 24, "pack_unit_product_name": "STELLA ARTOIS GF 600ML RETONAVEL"},
    {"name": "CX AMSTEL LT 473ML", "category": "Engradados", "price": 84.0, "cost": 50.4, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "AMSTEL LT 473ML"},
    {"name": "CX BRAHMA CHOPP LT 473ML", "category": "Engradados", "price": 84.0, "cost": 50.4, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "BRAHMA CHOPP LT 473ML"},
    {"name": "CX BRAHMA DM LT 350ML", "category": "Engradados", "price": 72.0, "cost": 42.0, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "BRAHMA DM LT 350ML"},
    {"name": "CX BUDWEISER LT 473ML", "category": "Engradados", "price": 84.0, "cost": 50.4, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "BUDWEISER LT 473ML"},
    {"name": "CX CORONA LT 473ML", "category": "Engradados", "price": 108.0, "cost": 78.0, "stock": 10, "min_stock": 3, "pack_size": 12, "pack_unit_product_name": "CORONA LT 473ML"},
    {"name": "CX HEINEKEN LT 473ML", "category": "Engradados", "price": 96.0, "cost": 60.0, "stock": 20, "min_stock": 6, "pack_size": 12, "pack_unit_product_name": "HEINEKEN LT 473ML"},
    {"name": "CX LAGUNITAS LT 350ML", "category": "Engradados", "price": 120.0, "cost": 78.0, "stock": 5, "min_stock": 2, "pack_size": 12, "pack_unit_product_name": "LAGUNITAS LT 350ML"},
    {"name": "CX ORIGINAL LT 473ML", "category": "Engradados", "price": 84.0, "cost": 50.4, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "ORIGINAL LT 473ML"},
    {"name": "CX SPATEN LT 473ML", "category": "Engradados", "price": 84.0, "cost": 50.4, "stock": 15, "min_stock": 5, "pack_size": 12, "pack_unit_product_name": "SPATEN LT 473ML"},
    {"name": "CX BUDWEISER LN 330ML", "category": "Engradados", "price": 54.0, "cost": 33.0, "stock": 10, "min_stock": 3, "pack_size": 6, "pack_unit_product_name": "BUDWEISER LN 330ML"},
    {"name": "CX CORONA LN 330ML", "category": "Engradados", "price": 60.0, "cost": 36.0, "stock": 10, "min_stock": 3, "pack_size": 6, "pack_unit_product_name": "CORONA LN 330ML"},
    {"name": "CX CORONA CERO LN 330ML", "category": "Engradados", "price": 60.0, "cost": 36.0, "stock": 5, "min_stock": 2, "pack_size": 6, "pack_unit_product_name": "CORONA CERO LN 330ML"},
    {"name": "CX HEINEKEN LN 330ML", "category": "Engradados", "price": 60.0, "cost": 36.0, "stock": 15, "min_stock": 4, "pack_size": 6, "pack_unit_product_name": "HEINEKEN LN 330ML"},
    {"name": "CX SKOL BEATS SENSES/GT LONGNECK", "category": "Engradados", "price": 72.0, "cost": 42.0, "stock": 8, "min_stock": 2, "pack_size": 6, "pack_unit_product_name": "SKOL BEATS SENSES/GT LONGNECK"},
    {"name": "CX STELLA ARTOIS PURE GOLD LN 330ML", "category": "Engradados", "price": 60.0, "cost": 36.0, "stock": 8, "min_stock": 2, "pack_size": 6, "pack_unit_product_name": "STELLA ARTOIS PURE GOLD LN 330ML"},
    {"name": "CX WEMIX SABORES", "category": "Engradados", "price": 54.0, "cost": 33.0, "stock": 8, "min_stock": 2, "pack_size": 6, "pack_unit_product_name": "WEMIX SABORES"},
    {"name": "CX BRAHMA CHOPP LITRINHO 300ML", "category": "Engradados", "price": 115.0, "cost": 64.4, "stock": 6, "min_stock": 2, "pack_size": 23, "pack_unit_product_name": "BRAHMA CHOPP LITRINHO 300ML"},
    {"name": "CX ORIGINAL LITRINHO 300ML", "category": "Engradados", "price": 115.0, "cost": 64.4, "stock": 6, "min_stock": 2, "pack_size": 23, "pack_unit_product_name": "ORIGINAL LITRINHO 300ML"},
]

SEED_USERS = [
    {
        "username": "sem_nome",
        "password": "123456",
        "name": "Sem nome",
        "role": "garcom",
        "is_registered": False,
    },
    {
        "username": "gerente",
        "password": "admin123",
        "name": "Gerente",
        "role": "gerente",
        "is_registered": True,
    },
    {
        "username": "caixa",
        "password": "caixa123",
        "name": "Caixa",
        "role": "caixa",
        "is_registered": True,
    },
    {
        "username": "estoquista",
        "password": "estoque123",
        "name": "Estoquista",
        "role": "estoquista",
        "is_registered": True,
    },
]

SEED_SETTINGS = [
    {"key": "store_name", "value": "Lads Beer", "label": "Nome do Estabelecimento", "description": "Nome exibido no sistema e nos tickets", "type": "string"},
    {"key": "store_address", "value": "", "label": "Endereço", "description": "Endereço do estabelecimento", "type": "string"},
    {"key": "store_phone", "value": "", "label": "Telefone", "description": "Telefone de contato", "type": "string"},
    {"key": "store_cnpj", "value": "", "label": "CNPJ", "description": "CNPJ do estabelecimento", "type": "string"},
    {"key": "service_charge_pct", "value": "10", "label": "Taxa de Serviço (%)", "description": "Percentual sugerido no fechamento da mesa", "type": "number"},
    {"key": "card_fee_debit_pct", "value": "1.5", "label": "Taxa Cartão de Débito (%)", "description": "Percentual de taxa para pagamento em débito (padrão)", "type": "number"},
    {"key": "card_fee_credit_pct", "value": "3.5", "label": "Taxa Cartão de Crédito (%)", "description": "Percentual de taxa para pagamento em crédito (padrão)", "type": "number"},
    {"key": "card_machine_1_name", "value": "Maquininha 1", "label": "Nome Maquininha 1", "description": "Nome da primeira maquininha de cartão", "type": "string"},
    {"key": "card_machine_1_debit_fee", "value": "1.5", "label": "Taxa Débito Maquininha 1 (%)", "description": "Taxa de débito da maquininha 1", "type": "number"},
    {"key": "card_machine_1_credit_fee", "value": "3.5", "label": "Taxa Crédito Maquininha 1 (%)", "description": "Taxa de crédito da maquininha 1", "type": "number"},
    {"key": "card_machine_2_name", "value": "Maquininha 2", "label": "Nome Maquininha 2", "description": "Nome da segunda maquininha de cartão", "type": "string"},
    {"key": "card_machine_2_debit_fee", "value": "2.0", "label": "Taxa Débito Maquininha 2 (%)", "description": "Taxa de débito da maquininha 2", "type": "number"},
    {"key": "card_machine_2_credit_fee", "value": "4.0", "label": "Taxa Crédito Maquininha 2 (%)", "description": "Taxa de crédito da maquininha 2", "type": "number"},
    {"key": "ticket_header", "value": "Lads Beer", "label": "Cabeçalho do Ticket", "description": "Texto do cabeçalho impresso nas comandas", "type": "string"},
    {"key": "ticket_footer", "value": "Obrigado pela preferência!", "label": "Rodapé do Ticket", "description": "Texto do rodapé impresso nas comandas", "type": "string"},
    {"key": "auto_open_enabled", "value": "false", "label": "Abrir Caixa Automaticamente", "description": "Ativa abertura automática do caixa no horário configurado", "type": "boolean"},
    {"key": "auto_open_time", "value": "18:00", "label": "Horário de Abertura Automática", "description": "Horário para abrir o caixa automaticamente (HH:MM)", "type": "string"},
    {"key": "auto_close_enabled", "value": "false", "label": "Notificar Fechamento Automaticamente", "description": "Ativa notificação/relatório automático no horário de fechamento", "type": "boolean"},
    {"key": "auto_close_time", "value": "00:00", "label": "Horário de Fechamento Automático", "description": "Horário para enviar relatório de fechamento (HH:MM)", "type": "string"},
    {"key": "auto_report_email", "value": "", "label": "Email para Relatório Automático", "description": "Email que recebe o relatório ao fechar o caixa", "type": "string"},
    {"key": "smtp_host", "value": "", "label": "Servidor SMTP", "description": "Servidor SMTP para envio de emails (ex: smtp.gmail.com)", "type": "string"},
    {"key": "smtp_port", "value": "587", "label": "Porta SMTP", "description": "Porta do servidor SMTP", "type": "number"},
    {"key": "smtp_user", "value": "", "label": "Usuário SMTP", "description": "Usuário/email para autenticação no SMTP", "type": "string"},
    {"key": "smtp_password", "value": "", "label": "Senha SMTP", "description": "Senha ou app password do SMTP", "type": "string"},
    {"key": "smtp_from", "value": "", "label": "Email Remetente", "description": "Email que aparecerá como remetente", "type": "string"},
    {"key": "printer_1_name", "value": "Impressora Cozinha", "label": "Nome da Impressora 1", "description": "Nome de identificação da primeira impressora térmica", "type": "string"},
    {"key": "printer_1_ip", "value": "192.168.1.101", "label": "IP da Impressora 1", "description": "Endereço IP da primeira impressora térmica (sugestão: 192.168.1.101)", "type": "string"},
    {"key": "printer_1_port", "value": "9100", "label": "Porta da Impressora 1", "description": "Porta de rede da primeira impressora térmica (padrão 9100)", "type": "number"},
    {"key": "printer_1_width", "value": "48", "label": "Largura da Impressora 1 (colunas)", "description": "Número de colunas de texto (32 para 58mm, 48 para 80mm)", "type": "number"},
    {"key": "printer_2_name", "value": "Impressora Bar", "label": "Nome da Impressora 2", "description": "Nome de identificação da segunda impressora térmica", "type": "string"},
    {"key": "printer_2_ip", "value": "192.168.1.102", "label": "IP da Impressora 2", "description": "Endereço IP da segunda impressora térmica (sugestão: 192.168.1.102)", "type": "string"},
    {"key": "printer_2_port", "value": "9100", "label": "Porta da Impressora 2", "description": "Porta de rede da segunda impressora térmica (padrão 9100)", "type": "number"},
    {"key": "printer_2_width", "value": "48", "label": "Largura da Impressora 2 (colunas)", "description": "Número de colunas de texto (32 para 58mm, 48 para 80mm)", "type": "number"},
    {"key": "printer_nota", "value": "1", "label": "Impressora para Nota", "description": "Qual impressora imprime a nota não fiscal (1 ou 2)", "type": "string"},
    {"key": "printer_cozinha", "value": "1", "label": "Impressora para Cozinha", "description": "Qual impressora imprime pedidos da cozinha (1 ou 2)", "type": "string"},
    {"key": "printer_bar", "value": "2", "label": "Impressora para Bar", "description": "Qual impressora imprime pedidos do bar (1 ou 2)", "type": "string"},
    {"key": "theme_mode", "value": "dark", "label": "Tema da Interface", "description": "Modo de exibição do sistema: claro (light) ou escuro (dark)", "type": "string"},
]

async def _ensure_columns() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS partial_service_charge FLOAT NOT NULL DEFAULT 0.0"
            )
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS code VARCHAR(50) UNIQUE DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS cost FLOAT NOT NULL DEFAULT 0.0")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS margin_pct FLOAT NOT NULL DEFAULT 0.0")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE")
        )
        await conn.execute(
            text("ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES orders(id)")
        )
        await conn.execute(
            text("ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS table_id INTEGER REFERENCES tables(id)")
        )
        await conn.execute(
            text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id)")
        )
        await conn.execute(
            text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS card_machine VARCHAR(30) DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS closed_by_id INTEGER REFERENCES users(id)")
        )
        await conn.execute(
            text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS closed_waiter_id INTEGER REFERENCES employees(id)")
        )
        await conn.execute(
            text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS service_charge_amount FLOAT NOT NULL DEFAULT 0.0")
        )
        await conn.execute(
            text(
                "UPDATE orders SET closed_by_id = waiter_id "
                "WHERE closed_by_id IS NULL AND status = 'finalizada'"
            )
        )
        await conn.execute(
            text(
                "UPDATE orders SET service_charge_amount = partial_service_charge + "
                "CASE WHEN service_charge_applied THEN GREATEST(0, total - partial_payment) * (service_charge_pct / 100) "
                "ELSE 0 END "
                "WHERE status = 'finalizada' AND service_charge_amount = 0"
            )
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS printer VARCHAR(20) DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS unit_cost FLOAT DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE order_rounds ADD COLUMN IF NOT EXISTS observation VARCHAR(255) DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS consignment_order_id INTEGER REFERENCES consignment_orders(id)")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
        )
        await conn.execute(
            text("DROP TABLE IF EXISTS printer_category")
        )
        await conn.execute(
            text("DROP TABLE IF EXISTS printers")
        )


async def _ensure_categories() -> None:
    async with async_session() as session:
        existing = await session.execute(select(Category.name))
        existing_names = {row[0].lower() for row in existing.all()}

        product_categories = await session.execute(
            select(Product.category).distinct().where(Product.category.is_not(None))
        )
        product_names = [row[0] for row in product_categories.all() if row[0]]

        # Explicit mapping of product categories to the printer that handles them.
        # Any category not listed here defaults to the bar printer.
        category_printer_map = {
            "Espetinhos": "cozinha",
            "Salgadinhos": "cozinha",
            "Carvão e Gelo": "bar",
            "Cervejas Garrafas 600ml": "bar",
            "Cervejas Latas": "bar",
            "Cervejas Litrinho 300ml": "bar",
            "Cervejas Longnecks": "bar",
            "Copão e Doses": "bar",
            "Engradados": "bar",
            "Gin, Vodkas, Rum e Bitter": "bar",
            "Whiskies": "bar",
            "Água, Refrigerantes e Energéticos": "bar",
        }

        for name in product_names:
            lower = name.lower()
            if lower in existing_names:
                continue
            printer = category_printer_map.get(name, "bar")
            session.add(Category(name=name, printer=printer))
            existing_names.add(lower)

        await session.commit()


async def ensure_settings(session) -> None:
    for s in SEED_SETTINGS:
        existing = await session.execute(select(Setting).where(Setting.key == s["key"]))
        if existing.scalar_one_or_none() is None:
            session.add(Setting(**s))


async def seed_pack_products(session) -> None:
    """Create pack products linked to unit products from the spreadsheet."""
    existing = await session.execute(select(Product).limit(1))
    if existing.scalar_one_or_none() is None:
        return

    existing_pack = await session.execute(select(Product).where(Product.category == "Engradados").limit(1))
    if existing_pack.scalar_one_or_none() is not None:
        return

    result = await session.execute(select(Product))
    unit_products = {p.name: p for p in result.scalars().all()}

    for pack_data in SEED_PACK_PRODUCTS:
        unit_name = pack_data["pack_unit_product_name"]
        unit_product = unit_products.get(unit_name)
        if not unit_product:
            print(f"[seed] Unit product not found for pack: {unit_name}")
            continue

        pack = Product(
            name=pack_data["name"],
            category=pack_data["category"],
            price=pack_data["price"],
            stock=pack_data["stock"],
            min_stock=pack_data["min_stock"],
            pack_size=pack_data["pack_size"],
            pack_unit_product_id=unit_product.id,
        )
        session.add(pack)

    await session.commit()


async def run_seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _ensure_columns()

    async with async_session() as session:
        await ensure_settings(session)

        existing = await session.execute(select(User).limit(1))
        if existing.scalar_one_or_none() is not None:
            await session.commit()
            return

        for t in SEED_TABLES:
            session.add(Table(**t))

        for p in SEED_PRODUCTS:
            session.add(Product(**p))

        for u in SEED_USERS:
            session.add(
                User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    name=u["name"],
                    role=u["role"],
                    is_registered=u["is_registered"],
                )
            )

        await session.commit()

        # Create pack products linked to the unit products just inserted.
        await seed_pack_products(session)

    # Ensure categories are created after products are committed so that
    # category-to-printer mapping can be inferred from the product categories.
    await _ensure_categories()
