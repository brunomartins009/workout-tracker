# Workout Tracker

Aplicação web local para registrar treinos de academia e acompanhar evolução.

## Pré-requisitos

- Python 3.11 ou superior

## Instalação

Crie e ative um ambiente virtual, depois instale as dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Executar os testes

```powershell
pytest
```

Os testes usam um banco SQLite temporário e não acessam o banco local da aplicação.

## Iniciar a aplicação

```powershell
flask --app run run
```

O arquivo SQLite local é criado automaticamente em `instance/workout_tracker.db`.
