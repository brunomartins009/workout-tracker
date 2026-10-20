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

## Backups automáticos e restauração

Quando uma nova versão precisa atualizar o esquema de um banco existente, a aplicação, ao iniciar, cria antes um backup e o verifica (abertura, verificação de integridade do SQLite e mesma quantidade de linhas em cada tabela). Só então o banco é atualizado. Sem atualização pendente, nenhum backup é criado.

- Os backups ficam em `instance/backups/`, com nomes como `workout_tracker.before-upgrade-20261019-153000.db`. Nenhum backup é sobrescrito, apagado automaticamente ou versionado no Git.
- O log de inicialização informa o nome do backup criado.
- Se o backup não puder ser criado ou verificado, a aplicação não inicia e o banco não é alterado.
- Se a atualização falhar depois do backup, a aplicação não inicia, o backup é mantido e nada é restaurado automaticamente.

Para restaurar um backup:

1. Pare a aplicação (Ctrl+C no terminal do `flask run`) e confirme que nenhum outro processo está usando o banco. Substituir o arquivo com a aplicação em execução pode corromper os dados.
2. Escolha o backup em `instance/backups/`: o nome indicado no log ou o mais recente anterior ao problema.
3. Guarde o banco atual com outro nome, sem apagá-lo, junto com os arquivos `-wal` e `-shm`, se existirem:

   ```powershell
   Rename-Item instance\workout_tracker.db workout_tracker.replaced-20261019.db
   ```

4. Copie (não mova) o backup para o lugar do banco:

   ```powershell
   Copy-Item instance\backups\workout_tracker.before-upgrade-20261019-153000.db instance\workout_tracker.db
   ```

5. Opcionalmente, confirme a integridade (deve mostrar `('ok',)`):

   ```powershell
   python -c "import sqlite3; c = sqlite3.connect('instance/workout_tracker.db'); print(c.execute('PRAGMA integrity_check').fetchone()); c.close()"
   ```

6. Se a atualização tinha falhado, corrija a causa antes de iniciar de novo: a mesma versão da aplicação tentará a atualização outra vez (com um novo backup).

## Biblioteca de exercícios

Os exercícios são uma biblioteca fixa da aplicação, definida em `app/exercise_library.py`. Eles não são criados nem editados pela interface.

Depois de alterar a lista (ou na primeira execução), sincronize o banco:

```powershell
flask --app run sync-exercise-library
```

O comando cria os exercícios que faltam e atualiza grupo/subgrupo dos existentes, reconhecendo-os pelo nome. Ele nunca apaga exercícios nem muda seus ids, então treinos e séries já registrados são preservados. `XXXXX` indica uma classificação ainda pendente.
