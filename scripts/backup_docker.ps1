param(
    [string]$OutputDir = "backups",
    [string]$PostgresService = "postgres",
    [string]$Database = "strata",
    [string]$User = "strata",
    [string]$ComposeProject = "strata"
)

python -m strata.backup backup-docker `
    --output-dir $OutputDir `
    --postgres-service $PostgresService `
    --database $Database `
    --user $User `
    --compose-project $ComposeProject
