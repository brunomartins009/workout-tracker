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

## Biblioteca de exercícios

Os exercícios são uma biblioteca fixa da aplicação, definida em `app/exercise_library.py`. Eles não são criados nem editados pela interface.

Depois de alterar a lista (ou na primeira execução), sincronize o banco:

```powershell
flask --app run sync-exercise-library
```

O comando cria os exercícios que faltam e atualiza grupo/subgrupo dos existentes, reconhecendo-os pelo nome. Ele nunca apaga exercícios nem muda seus ids, então treinos e séries já registrados são preservados. `XXXXX` indica uma classificação ainda pendente.
