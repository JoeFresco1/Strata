param(
    [Parameter(Mandatory = $true)]
    [string]$Backup,
    [Parameter(Mandatory = $true)]
    [string]$Confirm,
    [string]$PostgresService = "postgres",
    [string]$Database = "strata",
    [string]$User = "strata"
)

python -m strata.backup restore-docker `
    --backup $Backup `
    --confirm $Confirm `
    --postgres-service $PostgresService `
    --database $Database `
    --user $User
