# Откат ветки A+D

Все изменения A+D сделаны в ветке **`feature/ad-ui-improvements`**.

## Быстрый откат (оба репозитория)

### Бот (`G:\проги\ss`)

```powershell
cd G:\проги\ss
git checkout main
git branch -D feature/ad-ui-improvements
```

### Webapp (`G:\проги\webapp`)

```powershell
cd G:\проги\webapp
git checkout main
git branch -D feature/ad-ui-improvements
```

После этого перезапустите бота и (при необходимости) redeploy webapp с `main`.

## Если уже закоммитили в feature-ветку

```powershell
git checkout main
git branch -D feature/ad-ui-improvements
```

## Если нужно оставить фикс 2v2, но убрать только UI

На `ss` откатите только webapp, бэкенд battle-by-time можно оставить — он обратно совместим.

## Проверка текущей ветки

```powershell
git branch --show-current
```

Должно быть `feature/ad-ui-improvements` пока тестируете.
