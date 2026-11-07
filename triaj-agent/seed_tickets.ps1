$tickets = Get-Content -Raw -Path ".\seed_tickets.json" | ConvertFrom-Json
$url = "http://localhost:8000/tickets"
$i = 0
foreach ($t in $tickets) {
    $i++
    $body = @{ text = $t.text; submitted_by = $t.submitted_by } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType "application/json; charset=utf-8"
        Write-Host "[$i/$($tickets.Count)] $($r.ticket.code) -> $($r.ticket.status) ($($r.ticket.priority)/$($r.ticket.team))"
    } catch {
        Write-Host "[$i/$($tickets.Count)] EROARE: $($_.Exception.Message)"
    }
    Start-Sleep -Milliseconds 800
}
