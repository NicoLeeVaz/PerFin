Attribute VB_Name = "PerFinLauncher"
' PerFin core shell (task 2c): module launcher.
' Lists come from the perfin_modules table (written by the Python registry, which
' validates each module_manifest.json with the contract, writes_ledger false).
' Opens a module's OWN workbook file from <modules folder>\<module_dir>\<workbook_file>.
' The core workbook never edits module workbooks, and modules never edit this one.
Option Explicit

Public Function PerFin_ModulesDir() As String
    Dim v As String
    v = PerFin_Setting("PerFin_ModulesDir")
    If Len(v) = 0 Then v = PerFin_DataRoot() & "\workbooks"
    Do While Len(v) > 3 And Right$(v, 1) = "\"
        v = Left$(v, Len(v) - 1)
    Loop
    PerFin_ModulesDir = v
End Function

Public Function PerFin_ModulePath(ByVal moduleId As String, ByRef why As String) As String
    Dim lo As ListObject, r As ListRow, dirName As String, wbFile As String, p As String
    Set lo = PerFin_FindTable("perfin_modules")
    If lo Is Nothing Then why = "module table not found": Exit Function
    For Each r In lo.ListRows
        If CStr(r.Range.Cells(1, lo.ListColumns("module_id").Index).Value) = moduleId Then
            If CStr(r.Range.Cells(1, lo.ListColumns("status").Index).Value) <> "OK" Or _
               r.Range.Cells(1, lo.ListColumns("launchable").Index).Value <> True Then
                why = "module is not launchable: " & CStr(r.Range.Cells(1, lo.ListColumns("message").Index).Value)
                Exit Function
            End If
            dirName = CStr(r.Range.Cells(1, lo.ListColumns("module_dir").Index).Value)
            wbFile = CStr(r.Range.Cells(1, lo.ListColumns("workbook_file").Index).Value)
            If Not PerFin_IsPlainName(dirName) Or Not PerFin_IsPlainName(wbFile) Then
                why = "module folder or workbook name is not a plain file name": Exit Function
            End If
            If Not (LCase$(wbFile) Like "*.xlsx" Or LCase$(wbFile) Like "*.xlsm") Then
                why = "module workbook must be .xlsx or .xlsm": Exit Function
            End If
            If LCase$(wbFile) = LCase$(ThisWorkbook.Name) Or LCase$(wbFile) Like "perfin-core.xls?" Then
                why = "a module must ship its own workbook, not the core workbook": Exit Function
            End If
            p = PerFin_ModulesDir() & "\" & dirName & "\" & wbFile
            If Not PerFin_IsLocalPath(p) Then why = "modules folder is not a local folder": Exit Function
            If Len(Dir$(p)) = 0 Then why = "workbook file not found: " & p: Exit Function
            PerFin_ModulePath = p
            Exit Function
        End If
    Next r
    why = "unknown module " & moduleId
End Function

Public Sub PerFin_LaunchModule()
    Dim lo As ListObject, moduleId As String, why As String, p As String, sel As Range, wb As Workbook
    Set lo = PerFin_FindTable("perfin_modules")
    If lo Is Nothing Then Exit Sub
    If TypeName(Selection) = "Range" And Not lo.DataBodyRange Is Nothing Then
        Set sel = Intersect(Selection, lo.DataBodyRange)
        If Not sel Is Nothing Then
            moduleId = CStr(lo.DataBodyRange.Cells(sel.Row - lo.HeaderRowRange.Row, _
                            lo.ListColumns("module_id").Index).Value)
        End If
    End If
    If Len(moduleId) = 0 Then moduleId = Trim$(InputBox("Module id to open (see the Modules sheet):", "PerFin modules"))
    If Len(moduleId) = 0 Then Exit Sub
    p = PerFin_ModulePath(moduleId, why)
    If Len(p) = 0 Then
        MsgBox "Cannot open module " & moduleId & ": " & why, vbExclamation, "PerFin modules"
        Exit Sub
    End If
    For Each wb In Application.Workbooks
        If LCase$(wb.FullName) = LCase$(p) Then
            wb.Activate
            Exit Sub
        End If
    Next wb
    Workbooks.Open Filename:=p, UpdateLinks:=0, AddToMru:=False
End Sub
