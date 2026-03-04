# API Эндпоинты для Telegram Mini App

## Базовый URL
```
https://aliks.fun/api/v1
```

## Авторизация

Все защищённые эндпоинты требуют заголовок:
```
X-Telegram-Init-Data: <initData от Telegram WebApp>
```

Получить `initData` можно так:
```javascript
const initData = window.Telegram.WebApp.initData;
```

## Эндпоинты

### 1. Парсинг FUCHS (синхронизация из почты)

**POST** `/sync-now/`

Запускает парсинг писем FUCHS из почты и создание сделок в Bitrix24.

**Заголовки:**
- `X-Telegram-Init-Data`: обязательный

**Ответ:**
```json
{
  "task_id": "abc123-def456-...",
  "status": "queued"
}
```

**Пример запроса:**
```javascript
const response = await fetch('https://aliks.fun/api/v1/sync-now/', {
  method: 'POST',
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData,
    'Content-Type': 'application/json'
  }
});

const data = await response.json();
console.log('Task ID:', data.task_id);
```

**Проверка статуса задачи:**
```
GET /sync-now/status/{task_id}
```

**Ответ:**
```json
{
  "task_id": "abc123-def456-...",
  "status": "SUCCESS" | "PENDING" | "FAILURE",
  "result": null | "результат задачи"
}
```

**Возможные статусы:**
- `PENDING` - задача в очереди или выполняется
- `SUCCESS` - задача выполнена успешно
- `FAILURE` - задача завершилась с ошибкой

**Ошибки:**
- `401` - не авторизован (неверный Telegram initData)
- `429` - синхронизация уже запущена, подождите 10 минут

---

### 2. Генерация PDF для коммерческого предложения

**POST** `/offers/{offer_id}/generate-pdf`

Запускает генерацию PDF для коммерческого предложения. Генерация выполняется асинхронно.

**Параметры пути:**
- `offer_id` (int) - ID коммерческого предложения

**Заголовки:**
- `X-Telegram-Init-Data`: обязательный

**Ответ:**
```json
{
  "task_id": "abc123-def456-...",
  "status": "queued",
  "message": "PDF generation started"
}
```

**Пример запроса:**
```javascript
const offerId = 123;
const response = await fetch(`https://aliks.fun/api/v1/offers/${offerId}/generate-pdf`, {
  method: 'POST',
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData,
    'Content-Type': 'application/json'
  }
});

const data = await response.json();
console.log('Task ID:', data.task_id);
```

**Ошибки:**
- `401` - не авторизован
- `404` - коммерческое предложение не найдено
- `400` - коммерческое предложение пустое (нет товаров)

**Примечание:** После генерации PDF статус сделки в Bitrix24 автоматически меняется на "КП создано" (KP_CREATED).

---

## Дополнительные полезные эндпоинты

### Получить коммерческое предложение

**GET** `/offers/{offer_id}`

**Ответ:**
```json
{
  "id": 123,
  "status": "draft" | "generated" | "converted",
  "total": 15000.50,
  "bitrix_deal_id": 456,
  "items": [
    {
      "sku": "ABC123",
      "name": "Товар 1",
      "price": 1000.00,
      "quantity": 2,
      "total": 2000.00
    }
  ]
}
```

### Создать черновик коммерческого предложения

**POST** `/offers/draft`

**Ответ:**
```json
{
  "offer_id": 123
}
```

### Добавить товар в коммерческое предложение

**POST** `/offers/{offer_id}/add/{sku}`

**Параметры пути:**
- `offer_id` (int) - ID коммерческого предложения
- `sku` (string) - артикул товара

**Ответ:**
```json
{
  "status": "added"
}
```

### Удалить товар из коммерческого предложения

**DELETE** `/offers/{offer_id}/remove/{sku}`

**Параметры пути:**
- `offer_id` (int) - ID коммерческого предложения
- `sku` (string) - артикул товара

**Ответ:**
```json
{
  "status": "removed"
}
```

### Очистить коммерческое предложение

**POST** `/offers/{offer_id}/clear`

**Ответ:**
```json
{
  "status": "cleared"
}
```

### Конвертировать коммерческое предложение в сделку Bitrix24

**POST** `/offers/{offer_id}/convert`

**Ответ:**
```json
{
  "bitrix_deal_id": 456
}
```

---

## Примеры использования

### Полный цикл: создание КП и генерация PDF

```javascript
// 1. Создать черновик
const draftResponse = await fetch('https://aliks.fun/api/v1/offers/draft', {
  method: 'POST',
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData
  }
});
const { offer_id } = await draftResponse.json();

// 2. Добавить товары
await fetch(`https://aliks.fun/api/v1/offers/${offer_id}/add/ABC123`, {
  method: 'POST',
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData
  }
});

// 3. Сгенерировать PDF
const pdfResponse = await fetch(`https://aliks.fun/api/v1/offers/${offer_id}/generate-pdf`, {
  method: 'POST',
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData
  }
});
const { task_id } = await pdfResponse.json();

// 4. Проверить статус генерации (опционально)
const statusResponse = await fetch(`https://aliks.fun/api/v1/sync-now/status/${task_id}`, {
  headers: {
    'X-Telegram-Init-Data': window.Telegram.WebApp.initData
  }
});
const status = await statusResponse.json();
console.log('PDF generation status:', status.status);
```

---

## Коды ошибок

- `401` - Не авторизован (неверный или отсутствующий `X-Telegram-Init-Data`)
- `403` - Доступ запрещён (пользователь не зарегистрирован в системе)
- `404` - Ресурс не найден
- `400` - Неверный запрос (например, пустое коммерческое предложение)
- `429` - Слишком много запросов (например, синхронизация уже запущена)

---

## Примечания

1. Все эндпоинты требуют авторизации через Telegram WebApp `initData`
2. Генерация PDF и парсинг FUCHS выполняются асинхронно через Celery
3. После генерации PDF статус сделки в Bitrix24 автоматически обновляется
4. Парсинг FUCHS создаёт новые сделки в Bitrix24 в воронке "Гидротех"
