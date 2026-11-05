Attribute VB_Name = "PerfinSetup"
' PerFin Access setup helper (optional; exported VBA/DAO source as text).
' The primary setup is `python -m perfin_store.setup --create <path>`. Use this module only when
' Access rejects CREATE VIEW over ODBC (contract_meta.report_views = 'absent' or 'partial'):
' it saves each SELECT from access\schema\040_report_views.sql as a DAO saved query, which
' Excel/Power Query reads like a view. It never writes ledger data and makes no network calls.
' Not yet run on Windows [Unverified].
'
' Use: import this module into the PerFin .accdb (or a scratch front end linked to it), then in
' the Immediate window:   CreatePerfinReportQueries "C:\path\to\PerFin\access\schema\040_report_views.sql"
Option Compare Database
Option Explicit

Public Sub CreatePerfinReportQueries(ByVal scriptPath As String)
    Dim db As DAO.Database
    Dim text As String, stmts() As String, stmt As String
    Dim i As Long, p As Long, name As String, sqlText As String, created As Long
    Set db = CurrentDb
    text = StripComments(ReadScript(scriptPath))  ' comments first: they may contain ';'
    stmts = Split(text, ";")
    For i = LBound(stmts) To UBound(stmts)
        stmt = Trim$(Replace(stmts(i), vbCrLf, " "))
        If Left$(stmt, 12) = "CREATE VIEW " Then
            p = InStr(13, stmt, " AS ")
            name = Mid$(stmt, 13, p - 13)
            sqlText = Mid$(stmt, p + 4)
            On Error Resume Next
            db.QueryDefs.Delete name
            On Error GoTo 0
            db.CreateQueryDef name, sqlText
            created = created + 1
        End If
    Next i
    Debug.Print "PerFin: saved " & created & " report queries"
End Sub

Private Function ReadScript(ByVal path As String) As String
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.LoadFromFile path
    ReadScript = stream.ReadText
    stream.Close
End Function

Private Function StripComments(ByVal s As String) As String
    Dim lines() As String, i As Long, out As String
    lines = Split(Replace(s, vbCrLf, vbLf), vbLf)
    For i = LBound(lines) To UBound(lines)
        If Left$(LTrim$(lines(i)), 2) <> "--" Then out = out & lines(i) & vbCrLf
    Next i
    StripComments = out
End Function
