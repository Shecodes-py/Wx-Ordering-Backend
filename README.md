# WX Ordering API

A WhatsApp-based food ordering system. Customers place orders by chatting with a WhatsApp bot, and vendors manage everything through a dashboard API.

---

## How It Works

1. Customer messages the WhatsApp bot
2. Bot shows the menu, takes their order, and collects their delivery address
3. Customer pays via bank transfer (Squad virtual account) or chooses pay on delivery
4. Vendor sees the order in the dashboard and accepts or declines it
5. When the order is ready, vendor marks it complete — customer gets a WhatsApp notification
6. Customer sends feedback

---

## Tech Stack

| Layer | Tool |
|---|---|
| Framework | Django + Django REST Framework |
| Auth | JWT via `djangorestframework-simplejwt` |
| Database | PostgreSQL (Neon) |
| Media storage | Cloudinary |
| WhatsApp | Twilio |
| Payments | Squad |
| API Docs | drf-spectacular (Swagger + Redoc) |

---

## Project Structure

```
core/           → project config (settings, root urls)
profiles/       → customer profiles (phone, name, address)
dashboard/      → menu, orders, feedback, analytics (vendor-facing)
bot/            → WhatsApp webhook + conversation state
payments/       → Squad payment gateway + webhook
```

---

## Apps Explained

### profiles
Stores customer data created by the bot when a new customer messages for the first time.

- `phone_number` — unique identifier for each customer
- `full_name` — collected during onboarding
- `delivery_address` — where to send the food

### dashboard
The vendor's control panel. Four models live here:

**MenuItem** — food items with name, price, description, image, and availability toggle.

**Order** — created by the bot. Moves through statuses:
```
PENDING → ACTIVE → COMPLETED
         ↓
       DECLINED
```
Payment method is either `TRANSFER` (bank transfer via Squad) or `PAY_ON_DELIVERY`.

**OrderItem** — each food item inside an order. Stores a price snapshot so future price changes don't affect old orders.

**Feedback** — customer message tied to a completed order.

### bot
Handles incoming WhatsApp messages from Twilio. Tracks each customer's conversation state (where they are in the ordering flow) using `BotSession`.

### payments
Integrates with Squad payment gateway. Creates virtual accounts for bank transfer orders and listens for payment webhooks. Verifies webhook signatures with HMAC-SHA512 before touching the database.

---

## API Endpoints

### Auth
| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/auth/token/` | Get access + refresh tokens |
| POST | `/api/v1/auth/token/refresh/` | Refresh access token |

### Profiles
| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/profiles/` | List all customer profiles |
| GET | `/api/v1/profiles/{id}/` | Get a single profile |

### Menu
| Method | URL | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/menu/` | Required | List all menu items |
| POST | `/api/v1/menu/` | Required | Create a menu item |
| GET | `/api/v1/menu/{id}/` | Required | Get a menu item |
| PATCH | `/api/v1/menu/{id}/` | Required | Update a menu item |
| DELETE | `/api/v1/menu/{id}/` | Required | Delete a menu item |
| POST | `/api/v1/menu/{id}/toggle/` | Required | Toggle availability |
| GET | `/api/v1/menu/public/` | None | Public menu for bot/storefront |

### Orders
| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/orders/` | List all orders |
| GET | `/api/v1/orders/{id}/` | Get a single order |
| POST | `/api/v1/orders/{id}/accept/` | Accept a pending order |
| POST | `/api/v1/orders/{id}/decline/` | Decline a pending order |
| POST | `/api/v1/orders/{id}/complete/` | Complete an active order |

### Feedback
| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/feedback/` | List all feedback |
| GET | `/api/v1/feedback/{id}/` | Get a single feedback |

### Analytics
| Method | URL | Description |
|---|---|---|
| GET | `/api/v1/analytics/` | Revenue + order stats + 7-day trend |

### Payments
| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/payments/webhook/squad/` | Squad payment webhook |

### Bot
| Method | URL | Description |
|---|---|---|
| POST | `/api/v1/bot/webhook/` | Twilio WhatsApp webhook |

### API Docs
| URL | Description |
|---|---|
| `/api/schema/swagger-ui/` | Swagger UI |
| `/api/schema/redoc/` | Redoc |

---

## Environment Variables

```env
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

CLOUD_NAME=
API_KEY=
API_SECRET=

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

SQUAD_SECRET_KEY=
SQUAD_PUBLIC_KEY=
SQUAD_BASE_URL=https://api-d.squadco.com

CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
```

---

## Setup

```bash
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Mac/Linux

pip install -r requirements.txt

# fill in your .env file

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

---

## Key Design Decisions

- **Orders are read-only in the dashboard** — only the bot creates orders. Vendors can only transition their status.
- **Price snapshots** — `OrderItem.unit_price` is saved at order time, not linked live to `MenuItem.price`.
- **Webhook signature verification** — Squad webhooks are verified with HMAC-SHA512 before any database writes.
- **Atomic payment handling** — payment confirmation uses `select_for_update()` inside a transaction to prevent double-processing.
- **WhatsApp notifications outside transactions** — Twilio calls happen after the database transaction commits, so a failed message doesn't roll back the payment.