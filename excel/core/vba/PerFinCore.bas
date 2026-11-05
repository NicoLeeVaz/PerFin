Attribute VB_Name = "PerFinCore"
' PerFin core shell (task 2c): read-only refresh and shared helpers.
' Exported source text; import into PerFin-Core.xlsm (see docs/excel/windows-checklist.md).
' Rules: no network calls, no external processes, no object creation by ProgID.
' Refresh never writes back to any source. Sheet protection is a guard against
' accidental edits, not security and not encryption.
Option Explicit

Public Const PERFIN_REFRESH_ORDER As String = _
    "rpt_accounts,rpt_transactions,rpt_card_status,rpt_review_queue," & _
    "perfin_batch_versions,perfin_statement_recon,perfin_unreconciled_items,perfin_modules,perfin_refresh_status"

Private Type SYSTEMTIME
    wYear As Integer
    wMonth As Integer
    wDayOfWeek As Integer
    wDay As Integer
    wHour As Integer
    wMinute As Integer
    wSecond As Integer
    wMilliseconds As Integer
End Type

Private Type GUID_T
    Data1 As Long
    Data2 As Integer
    Data3 As Integer
    Data4(0 To 7) As Byte
End Type

#If VBA7 Then
Private Declare PtrSafe Sub GetSystemTime Lib "kernel32" (lpSystemTime As SYSTEMTIME)
Private Declare PtrSafe Function CoCreateGuid Lib "ole32" (pguid As GUID_T) As Long
#Else
Private Declare Sub GetSystemTime Lib "kernel32" (lpSystemTime As SYSTEMTIME)
Private Declare Function CoCreateGuid Lib "ole32" (pguid As GUID_T) As Long
#End If

' ---------------------------------------------------------------- settings

Public Function PerFin_Setting(ByVal name As String) As String
    PerFin_Setting = Trim$(CStr(ThisWorkbook.Names(name).RefersToRange.Value))
End Function

Public Function PerFin_DataRoot() As String
    Dim v As String
    v = PerFin_Setting("PerFin_DataRoot")
    If Len(v) = 0 Then v = Environ$("LOCALAPPDATA") & "\PerFin"
    Do While Len(v) > 3 And Right$(v, 1) = "\"
        v = Left$(v, Len(v) - 1)
    Loop
    PerFin_DataRoot = v
End Function

Public Function PerFin_IsLocalPath(ByVal p As String) As Boolean
    ' Absolute drive path only: no UNC/network share, no URL.
    PerFin_IsLocalPath = Len(p) >= 3 And Mid$(p, 2, 2) = ":\" And Left$(p, 2) <> "\\" _
        And InStr(1, p, "://") = 0 And (UCase$(Left$(p, 1)) Like "[A-Z]")
End Function

Public Function PerFin_IsPlainName(ByVal s As String) As Boolean
    Dim i As Long
    If Len(s) = 0 Or Len(s) > 85 Then Exit Function
    For i = 1 To Len(s)
        If Not (Mid$(s, i, 1) Like "[A-Za-z0-9_.-]") Then Exit Function
    Next i
    PerFin_IsPlainName = (Left$(s, 1) <> ".")
End Function

' ---------------------------------------------------------------- data-root location guard (1c)
' Same rules as evaluate_data_dir in config/privacy/perfin_privacy_checks.py. The lists are
' copied from config/privacy/defaults.json (data_dir.*); a Linux test keeps them equal.
' Sync folders and network paths are refused outright here (1c says "warn and block until
' acknowledged"; VBA has no acknowledgement store). Python promote re-checks every time.

Public Const PERFIN_SYNC_MARKERS As String = _
    "OneDrive|Dropbox|Google Drive|GoogleDrive|My Drive|iCloudDrive|iCloud Drive|Mobile Documents|" & _
    "Box|Box Sync|pCloud Drive|Nextcloud|ownCloud|MEGA|SynologyDrive|Sync"
Public Const PERFIN_SYNC_MARKER_PREFIXES As String = "OneDrive - "
Public Const PERFIN_SYNC_ENV_VARS As String = "OneDrive|OneDriveConsumer|OneDriveCommercial"
Public Const PERFIN_DATA_DIR_MARKER As String = "perfin-data-dir.json"

Private Function PathExists(ByVal p As String) As Boolean
    On Error GoTo Nope
    PathExists = Len(Dir$(p, vbDirectory Or vbHidden Or vbSystem Or vbReadOnly)) > 0
    Exit Function
Nope:
    PathExists = False
End Function

Public Function PerFin_IsUnder(ByVal child As String, ByVal parent As String) As Boolean
    Do While Len(parent) > 3 And Right$(parent, 1) = "\"
        parent = Left$(parent, Len(parent) - 1)
    Loop
    If Len(parent) = 0 Then Exit Function
    PerFin_IsUnder = (LCase$(child) = LCase$(parent)) Or _
        (LCase$(Left$(child, Len(parent) + 1)) = LCase$(parent & "\"))
End Function

Public Function PerFin_DataRootProblem(ByVal root As String) As String
    ' "" when root may hold PerFin data; otherwise the reason it is refused.
    Dim parts() As String, markers() As String, prefixes() As String, envs() As String
    Dim i As Long, j As Long, cur As String, v As String
    If Left$(root, 2) = "\\" Or Left$(root, 2) = "//" Then
        PerFin_DataRootProblem = "network (UNC) path": Exit Function
    End If
    If Not PerFin_IsLocalPath(root) Then
        PerFin_DataRootProblem = "not an absolute local drive path": Exit Function
    End If
    markers = Split(PERFIN_SYNC_MARKERS, "|")
    prefixes = Split(PERFIN_SYNC_MARKER_PREFIXES, "|")
    parts = Split(root, "\")
    For i = 1 To UBound(parts)
        For j = LBound(markers) To UBound(markers)
            If LCase$(parts(i)) = LCase$(markers(j)) Then
                PerFin_DataRootProblem = "sync folder segment: " & parts(i): Exit Function
            End If
        Next j
        For j = LBound(prefixes) To UBound(prefixes)
            If LCase$(Left$(parts(i), Len(prefixes(j)))) = LCase$(prefixes(j)) Then
                PerFin_DataRootProblem = "sync folder segment: " & parts(i): Exit Function
            End If
        Next j
    Next i
    envs = Split(PERFIN_SYNC_ENV_VARS, "|")
    For j = LBound(envs) To UBound(envs)
        v = Environ$(envs(j))
        If Len(v) > 0 Then
            If PerFin_IsUnder(root, v) Then PerFin_DataRootProblem = "under %" & envs(j) & "%": Exit Function
        End If
    Next j
    ' Walk the data root and every ancestor looking for a .git folder or file.
    cur = parts(0)
    If PathExists(cur & "\.git") Then PerFin_DataRootProblem = "inside a Git checkout: " & cur: Exit Function
    For i = 1 To UBound(parts)
        If Len(parts(i)) > 0 Then
            cur = cur & "\" & parts(i)
            If PathExists(cur & "\.git") Then
                PerFin_DataRootProblem = "inside a Git checkout: " & cur: Exit Function
            End If
        End If
    Next i
    If Not PathExists(root & "\" & PERFIN_DATA_DIR_MARKER) Then
        PerFin_DataRootProblem = "no " & PERFIN_DATA_DIR_MARKER & " marker; set the data root up first": Exit Function
    End If
End Function

Public Function PerFin_CheckedDataRoot() As String
    ' The data root, or an error when the location guard refuses it. Call before any write.
    Dim root As String, why As String
    root = PerFin_DataRoot()
    why = PerFin_DataRootProblem(root)
    If Len(why) > 0 Then Err.Raise vbObjectError + 530, "PerFin location check", _
        "PerFin data root refused (" & why & "): " & root
    PerFin_CheckedDataRoot = root
End Function

' ---------------------------------------------------------------- tables and protection

Public Function PerFin_FindTable(ByVal name As String) As ListObject
    Dim ws As Worksheet, lo As ListObject
    For Each ws In ThisWorkbook.Worksheets
        For Each lo In ws.ListObjects
            If lo.Name = name Then
                Set PerFin_FindTable = lo
                Exit Function
            End If
        Next lo
    Next ws
End Function

Public Sub PerFin_ProtectAll()
    Dim ws As Worksheet
    For Each ws In ThisWorkbook.Worksheets
        ws.Protect Contents:=True, DrawingObjects:=False, AllowFiltering:=True, _
            AllowFormattingColumns:=True, UserInterfaceOnly:=True
    Next ws
    ThisWorkbook.Protect Structure:=True
End Sub

Public Sub PerFin_UnprotectAll()
    Dim ws As Worksheet
    For Each ws In ThisWorkbook.Worksheets
        ws.Unprotect
    Next ws
End Sub

' ---------------------------------------------------------------- refresh (read-only)

Public Sub PerFin_Refresh()
    Dim root As String, days As Variant, names() As String, i As Long
    Dim lo As ListObject, failed As String, missing As String

    root = PerFin_DataRoot()
    If Not PerFin_IsLocalPath(root) Then
        MsgBox "PerFin data root must be a local folder such as C:\Users\<you>\AppData\Local\PerFin." & vbLf & _
               "Network shares and URLs are not allowed.", vbExclamation, "PerFin refresh"
        Exit Sub
    End If
    days = ThisWorkbook.Names("PerFin_StaleDays").RefersToRange.Value
    If Not IsNumeric(days) Then days = 7
    If days < 1 Or days > 365 Then days = 7

    On Error GoTo Abort
    SetParameter "PerFinDataRoot", """" & Replace(root, """", """""") & _
        """ meta [IsParameterQuery = true, Type = ""Text"", IsParameterQueryRequired = false]"
    SetParameter "PerFinStaleDays", CStr(CLng(days)) & _
        " meta [IsParameterQuery = true, Type = ""Number"", IsParameterQueryRequired = true]"
    On Error GoTo 0

    PerFin_UnprotectAll
    names = Split(PERFIN_REFRESH_ORDER, ",")
    For i = LBound(names) To UBound(names)
        Set lo = PerFin_FindTable(names(i))
        If lo Is Nothing Then
            missing = missing & vbLf & "  " & names(i)
        ElseIf Not RefreshTable(lo) Then
            ' Never leave old rows looking current: clear the table that failed.
            ClearTable lo
            failed = failed & vbLf & "  " & names(i)
        End If
    Next i
    PerFin_ProtectAll
    Application.CalculateFull

    If Len(failed) + Len(missing) = 0 Then
        MsgBox "Refreshed. Check the status banner before relying on the figures.", vbInformation, "PerFin refresh"
    Else
        MsgBox "Refresh problems. Affected tables were cleared:" & failed & _
               IIf(Len(missing) > 0, vbLf & "Tables not found (run PerFin_InstallQueries):" & missing, "") & _
               vbLf & "See the Status sheet.", vbCritical, "PerFin refresh"
    End If
    Exit Sub
Abort:
    MsgBox "PerFin refresh stopped before reading data: " & Err.Description & vbLf & _
           "Run PerFin_InstallQueries once to add the Power Query definitions.", vbCritical, "PerFin refresh"
End Sub

Private Sub SetParameter(ByVal name As String, ByVal formula As String)
    Dim q As WorkbookQuery
    Set q = ThisWorkbook.Queries(name)
    If q.Formula <> formula Then q.Formula = formula
End Sub

Private Function RefreshTable(ByVal lo As ListObject) As Boolean
    On Error GoTo Failed
    lo.QueryTable.BackgroundQuery = False
    lo.QueryTable.Refresh BackgroundQuery:=False
    RefreshTable = True
    Exit Function
Failed:
    RefreshTable = False
End Function

Private Sub ClearTable(ByVal lo As ListObject)
    On Error Resume Next
    If Not lo.DataBodyRange Is Nothing Then lo.DataBodyRange.ClearContents
    On Error GoTo 0
End Sub

' ---------------------------------------------------------------- command helpers

Public Function PerFin_JsonString(ByVal s As String) As String
    ' JSON string literal; everything outside printable ASCII is \u-escaped,
    ' so the file is plain ASCII whatever the Windows code page.
    Dim i As Long, code As Long, ch As String, out As String
    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        code = AscW(ch) And &HFFFF&
        Select Case code
            Case 34: out = out & "\"""
            Case 92: out = out & "\\"
            Case 8: out = out & "\b"
            Case 9: out = out & "\t"
            Case 10: out = out & "\n"
            Case 12: out = out & "\f"
            Case 13: out = out & "\r"
            Case 32 To 126: out = out & ch
            Case Else: out = out & "\u" & LCase$(Right$("000" & Hex$(code), 4))
        End Select
    Next i
    PerFin_JsonString = """" & out & """"
End Function

Public Function PerFin_UtcTimestamp() As String
    Dim st As SYSTEMTIME
    GetSystemTime st
    PerFin_UtcTimestamp = Format$(st.wYear, "0000") & "-" & Format$(st.wMonth, "00") & "-" & _
        Format$(st.wDay, "00") & "T" & Format$(st.wHour, "00") & ":" & Format$(st.wMinute, "00") & ":" & _
        Format$(st.wSecond, "00") & "Z"
End Function

Public Function PerFin_NewUuid() As String
    Dim g As GUID_T, i As Long, tail As String
    If CoCreateGuid(g) <> 0 Then Err.Raise vbObjectError + 513, "PerFin_NewUuid", "CoCreateGuid failed"
    For i = 2 To 7
        tail = tail & Right$("0" & Hex$(g.Data4(i)), 2)
    Next i
    PerFin_NewUuid = LCase$(Right$("0000000" & Hex$(g.Data1), 8) & "-" & _
        Right$("000" & Hex$(g.Data2 And &HFFFF&), 4) & "-" & _
        Right$("000" & Hex$(g.Data3 And &HFFFF&), 4) & "-" & _
        Right$("0" & Hex$(g.Data4(0)), 2) & Right$("0" & Hex$(g.Data4(1)), 2) & "-" & tail)
End Function

Public Sub PerFin_EnsureFolder(ByVal p As String)
    Dim parts() As String, i As Long, cur As String, root As String
    root = PerFin_CheckedDataRoot()          ' location guard before any MkDir
    If Not PerFin_IsUnder(p, root) Then Err.Raise vbObjectError + 532, "PerFin", "refusing to create folders outside the data root"
    parts = Split(p, "\")
    cur = parts(0)
    For i = 1 To UBound(parts)
        If Len(parts(i)) > 0 Then
            cur = cur & "\" & parts(i)
            If Len(Dir$(cur, vbDirectory)) = 0 Then MkDir cur
        End If
    Next i
End Sub

Public Sub PerFin_WriteNewAsciiFile(ByVal path As String, ByVal text As String)
    Dim f As Integer, root As String
    root = PerFin_CheckedDataRoot()          ' location guard before any Open/Print
    If Not PerFin_IsUnder(path, root) Then Err.Raise vbObjectError + 531, "PerFin", "refusing to write outside the data root"
    If Len(Dir$(path)) > 0 Then Err.Raise vbObjectError + 514, "PerFin", "file already exists: " & path
    f = FreeFile
    Open path For Output As #f
    Print #f, text
    Close #f
End Sub

Public Function PerFin_ReadTextFile(ByVal path As String) As String
    Dim f As Integer, line As String, out As String
    f = FreeFile
    Open path For Input As #f
    Do While Not EOF(f)
        Line Input #f, line
        out = out & line & vbCrLf
    Loop
    Close #f
    PerFin_ReadTextFile = out
End Function
