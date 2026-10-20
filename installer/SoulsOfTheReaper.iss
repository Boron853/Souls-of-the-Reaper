; Souls of the Reaper - standard Windows installer (Inno Setup)
; -----------------------------------------------------------------
; Unofficial PC port of Diablo III (Xbox 360) via the ReXGlue SDK.
;
; This is a plain, ordinary Windows setup wizard (Welcome / Select
; Destination / Start Menu Folder / custom "disc image" page / Ready /
; Installing / Finished) - no custom skin, no dark theme. It carries the
; compiled game binaries as regular installer payload and, during install,
; extracts the actual game assets from a user-supplied Diablo III (Xbox 360)
; disc image via tools\extract-xiso.exe.
;
; Build with (after Inno Setup is installed):
;   ISCC.exe installer\SoulsOfTheReaper.iss
;
; Language: chosen up front via Inno's own native "Select Setup Language"
; dialog (shown before the Welcome page), which also translates the wizard
; itself - not a separate mid-wizard page. Same choice drives the game's
; user_language/user_country (see GetLangIdCountryForActiveLanguage).
;
; Unattended install (/LANG is one of the [Languages] Names below - english/
; german/spanish/italian/portuguese; Inno's own built-in switch, defaults to
; english if omitted):
;   SoulsOfTheReaper_Setup.exe /VERYSILENT /ISO="D:\path\to\disc.iso" /LANG=german /SUPPRESSMSGBOXES

#define MyAppName "Souls of the Reaper"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "D3ReXPort"
#define MyAppURL "https://github.com/Boron853/Souls-of-the-Reaper"
#define MyAppExeName "SoulsOfTheReaper.exe"
#define RepoRoot "..\"
#define GameExeDir "..\port\out\build\win-amd64-relwithdebinfo"

[Setup]
AppId={{B4C3F210-8B2E-4B23-9B6D-2B6C7B6A1F3A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\SoulsOfTheReaper
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=auto
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=SoulsOfTheReaper_Setup
SetupIconFile={#RepoRoot}launcher\ico_launcher.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
; The game data extracted from the user's own disc (~7.5 GB) is written
; straight to {app}\game by our own code, not through [Files], so Inno's
; automatic free-space check on the "Select Destination" page needs a nudge
; to account for it.
ExtraDiskSpaceRequired=8000000000
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Choosing a language here is Inno's native mechanism: it shows its own
; "Select Setup Language" dialog BEFORE anything else (Welcome page
; included), translates the wizard's own buttons/labels/messages, exposes
; the choice to [Code] via ActiveLanguage, and is what the standard /LANG=
; command-line switch already selects for silent installs (LANG=german, not
; a custom param) - no custom code needed for any of that.
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
SelectDirDesc=
SelectStartMenuFolderDesc=
SelectTasksDesc=
ReadyLabel1=
; Our task section's own heading, in place of Inno's generic "Additional
; tasks:". ReadyMemoTasks is a plain heading string, shown flush-left at the
; SAME indent as the other Ready-page section titles (Destination location:,
; Start Menu folder:, etc) - unlike [Tasks]'s GroupDescription, which Inno
; always indents one level deeper as a sub-heading. So the label belongs
; here, not on GroupDescription (left blank below), to match how every other
; section title on this page is flush-left with its content indented once
; beneath it, rather than showing as a nested sub-heading.
; NOTE: [Messages] values are used as literal text, NOT constant-expanded -
; {cm:...} only works in [Files]/[Icons]/[Tasks]-style fields, so the
; translated text has to be written out directly per language below (not
; referenced via a [CustomMessages] entry).
ReadyMemoTasks=Shortcut:
german.ReadyMemoTasks=Verknüpfung:
spanish.ReadyMemoTasks=Acceso directo:
italian.ReadyMemoTasks=Collegamento:
portuguese.ReadyMemoTasks=Atalho:
russian.ReadyMemoTasks=Ярлык:

; Our own custom-page/status text (English default; per-language overrides
; below - Inno falls back to the unsuffixed value for any language that
; isn't overridden, so this line alone would still work for all 5, but the
; overrides make the installer's OWN language match its wizard language).
[CustomMessages]
IsoPageCaption=Select Your Disc Image
IsoPageDescription=Souls of the Reaper needs your own legally-owned Diablo III (Xbox 360, Ultimate Evil Edition) disc image.
IsoPageSubCaption=Select the location of the disc image (.iso / .xiso), then click Next.
IsoChecking=Disc image selected (%s GB). Checking language...
IsoDetected=Disc image selected (%s GB). Disc language: %s.
IsoDefault=Disc image selected (%s GB). Disc language: English (default).
StatusExtracting=Extracting disc image (this takes a few minutes)...
StatusExtractingProgress=Extracting disc image... (%s / %s GB)
StatusLocating=Locating game files...
StatusInstallingData=Installing game data...
StatusApplyingLang=Applying language selection...
StatusWritingConfig=Writing configuration...
StatusComplete=Installation complete.
InstallFailedMsg=Souls of the Reaper could not finish installing:
; Language names, used to translate the disc-language preview (IsoDetected)
; regardless of which of LocaleTable's ~18 locales was actually detected -
; covers every LangId that table can produce, not just the 5 offered above.
LangName_en=English
LangName_ja=Japanese
LangName_de=German
LangName_fr=French
LangName_es=Spanish
LangName_it=Italian
LangName_ko=Korean
LangName_zh=Chinese
LangName_pt=Portuguese
LangName_pl=Polish
LangName_ru=Russian
LangName_tr=Turkish

german.IsoPageCaption=Datenträgerabbild auswählen
german.IsoPageDescription=Souls of the Reaper benötigt dein eigenes, legal erworbenes Diablo III (Xbox 360, Ultimate Evil Edition) Datenträgerabbild.
german.IsoPageSubCaption=Wähle den Speicherort des Datenträgerabbilds (.iso / .xiso) und klicke auf Weiter.
german.IsoChecking=Datenträgerabbild ausgewählt (%s GB). Sprache wird geprüft...
german.IsoDetected=Datenträgerabbild ausgewählt (%s GB). Sprache des Datenträgers: %s.
german.IsoDefault=Datenträgerabbild ausgewählt (%s GB). Sprache des Datenträgers: Englisch (Standard).
german.StatusExtracting=Datenträgerabbild wird extrahiert (dauert einige Minuten)...
german.StatusExtractingProgress=Datenträgerabbild wird extrahiert... (%s / %s GB)
german.StatusLocating=Spieldateien werden gesucht...
german.StatusInstallingData=Spieldaten werden installiert...
german.StatusApplyingLang=Sprachauswahl wird angewendet...
german.StatusWritingConfig=Konfiguration wird geschrieben...
german.StatusComplete=Installation abgeschlossen.
german.InstallFailedMsg=Souls of the Reaper konnte nicht vollständig installiert werden:
german.LangName_en=Englisch
german.LangName_ja=Japanisch
german.LangName_de=Deutsch
german.LangName_fr=Französisch
german.LangName_es=Spanisch
german.LangName_it=Italienisch
german.LangName_ko=Koreanisch
german.LangName_zh=Chinesisch
german.LangName_pt=Portugiesisch
german.LangName_pl=Polnisch
german.LangName_ru=Russisch
german.LangName_tr=Türkisch

spanish.IsoPageCaption=Selecciona tu Imagen de Disco
spanish.IsoPageDescription=Souls of the Reaper necesita tu propia imagen de disco de Diablo III (Xbox 360, Ultimate Evil Edition) adquirida legalmente.
spanish.IsoPageSubCaption=Selecciona la ubicación de la imagen de disco (.iso / .xiso) y haz clic en Siguiente.
spanish.IsoChecking=Imagen de disco seleccionada (%s GB). Comprobando idioma...
spanish.IsoDetected=Imagen de disco seleccionada (%s GB). Idioma del disco: %s.
spanish.IsoDefault=Imagen de disco seleccionada (%s GB). Idioma del disco: Inglés (por defecto).
spanish.StatusExtracting=Extrayendo imagen de disco (esto toma unos minutos)...
spanish.StatusExtractingProgress=Extrayendo imagen de disco... (%s / %s GB)
spanish.StatusLocating=Localizando archivos del juego...
spanish.StatusInstallingData=Instalando datos del juego...
spanish.StatusApplyingLang=Aplicando selección de idioma...
spanish.StatusWritingConfig=Escribiendo configuración...
spanish.StatusComplete=Instalación completa.
spanish.InstallFailedMsg=Souls of the Reaper no pudo terminar de instalarse:
spanish.LangName_en=Inglés
spanish.LangName_ja=Japonés
spanish.LangName_de=Alemán
spanish.LangName_fr=Francés
spanish.LangName_es=Español
spanish.LangName_it=Italiano
spanish.LangName_ko=Coreano
spanish.LangName_zh=Chino
spanish.LangName_pt=Portugués
spanish.LangName_pl=Polaco
spanish.LangName_ru=Ruso
spanish.LangName_tr=Turco

italian.IsoPageCaption=Seleziona l'Immagine del Disco
italian.IsoPageDescription=Souls of the Reaper richiede la tua immagine disco di Diablo III (Xbox 360, Ultimate Evil Edition) posseduta legalmente.
italian.IsoPageSubCaption=Seleziona la posizione dell'immagine disco (.iso / .xiso), poi fai clic su Avanti.
italian.IsoChecking=Immagine disco selezionata (%s GB). Verifica della lingua...
italian.IsoDetected=Immagine disco selezionata (%s GB). Lingua del disco: %s.
italian.IsoDefault=Immagine disco selezionata (%s GB). Lingua del disco: Inglese (predefinita).
italian.StatusExtracting=Estrazione dell'immagine disco (richiede alcuni minuti)...
italian.StatusExtractingProgress=Estrazione dell'immagine disco... (%s / %s GB)
italian.StatusLocating=Ricerca dei file di gioco...
italian.StatusInstallingData=Installazione dei dati di gioco...
italian.StatusApplyingLang=Applicazione della selezione della lingua...
italian.StatusWritingConfig=Scrittura della configurazione...
italian.StatusComplete=Installazione completata.
italian.InstallFailedMsg=Impossibile completare l'installazione di Souls of the Reaper:
italian.LangName_en=Inglese
italian.LangName_ja=Giapponese
italian.LangName_de=Tedesco
italian.LangName_fr=Francese
italian.LangName_es=Spagnolo
italian.LangName_it=Italiano
italian.LangName_ko=Coreano
italian.LangName_zh=Cinese
italian.LangName_pt=Portoghese
italian.LangName_pl=Polacco
italian.LangName_ru=Russo
italian.LangName_tr=Turco

portuguese.IsoPageCaption=Selecione a Imagem do Disco
portuguese.IsoPageDescription=Souls of the Reaper precisa da sua própria imagem de disco de Diablo III (Xbox 360, Ultimate Evil Edition) adquirida legalmente.
portuguese.IsoPageSubCaption=Selecione a localização da imagem de disco (.iso / .xiso) e clique em Seguinte.
portuguese.IsoChecking=Imagem de disco selecionada (%s GB). A verificar o idioma...
portuguese.IsoDetected=Imagem de disco selecionada (%s GB). Idioma do disco: %s.
portuguese.IsoDefault=Imagem de disco selecionada (%s GB). Idioma do disco: Inglês (padrão).
portuguese.StatusExtracting=A extrair a imagem de disco (demora alguns minutos)...
portuguese.StatusExtractingProgress=A extrair a imagem de disco... (%s / %s GB)
portuguese.StatusLocating=A localizar os ficheiros do jogo...
portuguese.StatusInstallingData=A instalar os dados do jogo...
portuguese.StatusApplyingLang=A aplicar a seleção de idioma...
portuguese.StatusWritingConfig=A escrever a configuração...
portuguese.StatusComplete=Instalação concluída.
portuguese.InstallFailedMsg=Não foi possível concluir a instalação do Souls of the Reaper:
portuguese.LangName_en=Inglês
portuguese.LangName_ja=Japonês
portuguese.LangName_de=Alemão
portuguese.LangName_fr=Francês
portuguese.LangName_es=Espanhol
portuguese.LangName_it=Italiano
portuguese.LangName_ko=Coreano
portuguese.LangName_zh=Chinês
portuguese.LangName_pt=Português
portuguese.LangName_pl=Polaco
portuguese.LangName_ru=Russo
portuguese.LangName_tr=Turco

russian.IsoPageCaption=Выберите образ диска
russian.IsoPageDescription=Souls of the Reaper требует ваш собственный, законно приобретённый образ диска Diablo III (Xbox 360, Ultimate Evil Edition).
russian.IsoPageSubCaption=Укажите расположение образа диска (.iso / .xiso), затем нажмите «Далее».
russian.IsoChecking=Образ диска выбран (%s ГБ). Проверка языка...
russian.IsoDetected=Образ диска выбран (%s ГБ). Язык диска: %s.
russian.IsoDefault=Образ диска выбран (%s ГБ). Язык диска: английский (по умолчанию).
russian.StatusExtracting=Извлечение образа диска (это займёт несколько минут)...
russian.StatusExtractingProgress=Извлечение образа диска... (%s / %s ГБ)
russian.StatusLocating=Поиск файлов игры...
russian.StatusInstallingData=Установка данных игры...
russian.StatusApplyingLang=Применение выбора языка...
russian.StatusWritingConfig=Запись конфигурации...
russian.StatusComplete=Установка завершена.
russian.InstallFailedMsg=Не удалось завершить установку Souls of the Reaper:
russian.LangName_en=Английский
russian.LangName_ja=Японский
russian.LangName_de=Немецкий
russian.LangName_fr=Французский
russian.LangName_es=Испанский
russian.LangName_it=Итальянский
russian.LangName_ko=Корейский
russian.LangName_zh=Китайский
russian.LangName_pt=Португальский
russian.LangName_pl=Польский
russian.LangName_ru=Русский
russian.LangName_tr=Турецкий

[Tasks]
; No GroupDescription: the "Shortcut" heading now lives on ReadyMemoTasks
; above instead (flush-left, matching the other section titles on the Ready
; page) - a GroupDescription here would add a second, more-indented
; sub-heading underneath it for this single task, which is what looked wrong
; (the label sitting one level deeper than "Start Menu folder:" etc). Net
; result: "Shortcut:" flush-left, "Create a desktop icon" indented once
; beneath it - same pattern as every other section on the page.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"

[Files]
Source: "{#GameExeDir}\diablo3.exe";              DestDir: "{app}";       Flags: ignoreversion
Source: "{#GameExeDir}\rexruntimerd.dll";         DestDir: "{app}";       Flags: ignoreversion
Source: "{#GameExeDir}\rexgpu-xenosrd.dll";       DestDir: "{app}";       Flags: ignoreversion
Source: "{#RepoRoot}launcher\dist\SoulsOfTheReaper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}apply_config.ps1";            DestDir: "{app}";       Flags: ignoreversion
Source: "{#RepoRoot}tools\extract-xiso.exe";      DestDir: "{app}\tools"; Flags: ignoreversion
Source: "{#RepoRoot}tools\extract-xiso.exe";      DestDir: "{tmp}";       Flags: dontcopy

[Icons]
; IconFilename points at the launcher exe itself (which always carries
; ico_launcher.ico, embedded fresh by ps2exe on every build), not diablo3.exe
; - that exe's icon is a separate post-build resource patch (tools\set_game_icon.ps1)
; that gets lost on every rebuild/relink, so shortcuts pointing at it can end
; up with the generic Windows exe icon instead of the intended artwork.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
type
  TLocaleRow = record
    Prefix: string;
    LangId: Integer;
    CountryId: Integer;
    LocaleName: string;
  end;

  TIsoStartupInfo = record
    cb: Longint;
    lpReserved: string;
    lpDesktop: string;
    lpTitle: string;
    dwX: Longint;
    dwY: Longint;
    dwXSize: Longint;
    dwYSize: Longint;
    dwXCountChars: Longint;
    dwYCountChars: Longint;
    dwFillAttribute: Longint;
    dwFlags: Longint;
    wShowWindow: Word;
    cbReserved2: Word;
    lpReserved2: Longint;
    hStdInput: Longint;
    hStdOutput: Longint;
    hStdError: Longint;
  end;

  TIsoProcessInformation = record
    hProcess: Longint;
    hThread: Longint;
    dwProcessId: Longint;
    dwThreadId: Longint;
  end;

const
  IsoStartfUseShowWindow = $00000001;
  IsoCreateNoWindow      = $08000000;
  IsoWaitTimeout         = 258;
  IsoSwHide              = 0;

function CreateProcessW(lpApplicationName: string; lpCommandLine: string;
  lpProcessAttributes: Longint; lpThreadAttributes: Longint; bInheritHandles: Boolean;
  dwCreationFlags: Longint; lpEnvironment: Longint; lpCurrentDirectory: string;
  const lpStartupInfo: TIsoStartupInfo; var lpProcessInformation: TIsoProcessInformation): Boolean;
  external 'CreateProcessW@kernel32.dll stdcall';

function WaitForSingleObject(hHandle: Longint; dwMilliseconds: Longint): Longint;
  external 'WaitForSingleObject@kernel32.dll stdcall';

function GetExitCodeProcess(hProcess: Longint; var lpExitCode: Longint): Boolean;
  external 'GetExitCodeProcess@kernel32.dll stdcall';

function CloseHandle(hObject: Longint): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function MoveFileW(lpExistingFileName: string; lpNewFileName: string): Boolean;
  external 'MoveFileW@kernel32.dll stdcall';

var
  IsoPage: TInputFileWizardPage;
  IsoInfoLabel: TNewStaticText;
  LocaleTable: array[0..17] of TLocaleRow;
  GExtractError: string;

{ The game's language IS the installer's own wizard language now (chosen via
  Inno's native startup "Select Setup Language" dialog / the standard
  /LANG=<name> silent switch - see [Languages] above), not a separate custom
  page: ActiveLanguage returns the internal Name of whichever [Languages]
  entry is active. Keep in sync by hand with launcher\Launcher.ps1's
  $LangTable if a language is added/removed. }
procedure GetLangIdCountryForActiveLanguage(var LangId, CountryId: Integer);
begin
  case ActiveLanguage of
    'german':     begin LangId := 3; CountryId := 24;  end;
    'spanish':    begin LangId := 5; CountryId := 31;  end;
    'italian':    begin LangId := 6; CountryId := 50;  end;
    'portuguese': begin LangId := 9; CountryId := 84;  end;
    'russian':    begin LangId := 12; CountryId := 88; end;
  else
    begin LangId := 1; CountryId := 103; end; { english }
  end;
end;

{ Translates a detected disc LangId to a display name in the INSTALLER's own
  active language (LocaleTable's own LocaleName field is English-only, e.g.
  'Spanish' - shown verbatim regardless of ActiveLanguage, which reads wrong
  once the wizard itself isn't English). Covers every LangId LocaleTable can
  produce, not just the 5 languages selectable at startup. }
function GetLangDisplayName(LangId: Integer): string;
begin
  case LangId of
    2:  Result := CustomMessage('LangName_ja');
    3:  Result := CustomMessage('LangName_de');
    4:  Result := CustomMessage('LangName_fr');
    5:  Result := CustomMessage('LangName_es');
    6:  Result := CustomMessage('LangName_it');
    7:  Result := CustomMessage('LangName_ko');
    8:  Result := CustomMessage('LangName_zh');
    9:  Result := CustomMessage('LangName_pt');
    11: Result := CustomMessage('LangName_pl');
    12: Result := CustomMessage('LangName_ru');
    14: Result := CustomMessage('LangName_tr');
  else
    Result := CustomMessage('LangName_en');
  end;
end;

procedure InitLocaleTable;
begin
  { Kept in sync by hand with launcher\Launcher.ps1's $LangTable and the old
    installer\Setup.ps1's Get-LocaleFromCpkNames - not shared code, three
    independent copies, touch all three if a locale is added. }
  LocaleTable[0].Prefix  := 'enUS'; LocaleTable[0].LangId  := 1;  LocaleTable[0].CountryId  := 103; LocaleTable[0].LocaleName  := 'English';
  LocaleTable[1].Prefix  := 'enGB'; LocaleTable[1].LangId  := 1;  LocaleTable[1].CountryId  := 35;  LocaleTable[1].LocaleName  := 'English (UK)';
  LocaleTable[2].Prefix  := 'esES'; LocaleTable[2].LangId  := 5;  LocaleTable[2].CountryId  := 31;  LocaleTable[2].LocaleName  := 'Spanish';
  LocaleTable[3].Prefix  := 'esMX'; LocaleTable[3].LangId  := 5;  LocaleTable[3].CountryId  := 71;  LocaleTable[3].LocaleName  := 'Spanish (LatAm)';
  LocaleTable[4].Prefix  := 'frFR'; LocaleTable[4].LangId  := 4;  LocaleTable[4].CountryId  := 34;  LocaleTable[4].LocaleName  := 'French';
  LocaleTable[5].Prefix  := 'deDE'; LocaleTable[5].LangId  := 3;  LocaleTable[5].CountryId  := 24;  LocaleTable[5].LocaleName  := 'German';
  LocaleTable[6].Prefix  := 'itIT'; LocaleTable[6].LangId  := 6;  LocaleTable[6].CountryId  := 50;  LocaleTable[6].LocaleName  := 'Italian';
  LocaleTable[7].Prefix  := 'ptBR'; LocaleTable[7].LangId  := 9;  LocaleTable[7].CountryId  := 13;  LocaleTable[7].LocaleName  := 'Portuguese';
  LocaleTable[8].Prefix  := 'ptPT'; LocaleTable[8].LangId  := 9;  LocaleTable[8].CountryId  := 84;  LocaleTable[8].LocaleName  := 'Portuguese (Portugal)';
  LocaleTable[9].Prefix  := 'ruRU'; LocaleTable[9].LangId  := 12; LocaleTable[9].CountryId  := 88;  LocaleTable[9].LocaleName  := 'Russian';
  LocaleTable[10].Prefix := 'plPL'; LocaleTable[10].LangId := 11; LocaleTable[10].CountryId := 82;  LocaleTable[10].LocaleName := 'Polish';
  LocaleTable[11].Prefix := 'frCA'; LocaleTable[11].LangId := 4;  LocaleTable[11].CountryId := 16;  LocaleTable[11].LocaleName := 'French (Canada)';
  LocaleTable[12].Prefix := 'jaJP'; LocaleTable[12].LangId := 2;  LocaleTable[12].CountryId := 53;  LocaleTable[12].LocaleName := 'Japanese';
  LocaleTable[13].Prefix := 'koKR'; LocaleTable[13].LangId := 7;  LocaleTable[13].CountryId := 56;  LocaleTable[13].LocaleName := 'Korean';
  LocaleTable[14].Prefix := 'zhCN'; LocaleTable[14].LangId := 8;  LocaleTable[14].CountryId := 20;  LocaleTable[14].LocaleName := 'Chinese (Simplified)';
  LocaleTable[15].Prefix := 'zhTW'; LocaleTable[15].LangId := 8;  LocaleTable[15].CountryId := 101; LocaleTable[15].LocaleName := 'Chinese (Traditional)';
  LocaleTable[16].Prefix := 'trTR'; LocaleTable[16].LangId := 14; LocaleTable[16].CountryId := 99;  LocaleTable[16].LocaleName := 'Turkish';
  LocaleTable[17].Prefix := 'enSG'; LocaleTable[17].LangId := 1;  LocaleTable[17].CountryId := 91;  LocaleTable[17].LocaleName := 'English (SG)';
end;

{ Matches a "xxYY_Common.cpk" token (exactly 15 chars) against the locale
  table. Each Xbox 360 regional disc ships exactly one language pack, so in
  the normal case there's exactly one match; if more than one somehow shows
  up, prefer a non-English one (English is the likeliest leftover default,
  not the disc's actual language). }
function DetectLocaleFromNames(Names: TArrayOfString; var LangId, CountryId: Integer; var LocaleName: string): Boolean;
var
  i, j, FoundIdx, NonEnglishIdx: Integer;
  Prefix: string;
begin
  FoundIdx := -1;
  NonEnglishIdx := -1;
  for i := 0 to GetArrayLength(Names) - 1 do
  begin
    if (Length(Names[i]) = 15) and (Copy(Names[i], 5, 11) = '_Common.cpk') then
    begin
      Prefix := Copy(Names[i], 1, 4);
      for j := 0 to High(LocaleTable) do
      begin
        if LocaleTable[j].Prefix = Prefix then
        begin
          if FoundIdx = -1 then FoundIdx := j;
          if (LocaleTable[j].Prefix <> 'enUS') and (LocaleTable[j].Prefix <> 'enGB') and (NonEnglishIdx = -1) then
            NonEnglishIdx := j;
        end;
      end;
    end;
  end;
  if NonEnglishIdx <> -1 then FoundIdx := NonEnglishIdx;
  Result := FoundIdx <> -1;
  if Result then
  begin
    LangId := LocaleTable[FoundIdx].LangId;
    CountryId := LocaleTable[FoundIdx].CountryId;
    LocaleName := LocaleTable[FoundIdx].LocaleName;
  end else begin
    LangId := 1; CountryId := 103; LocaleName := 'English';
  end;
end;

function GetIsoPath(): string;
begin
  if WizardSilent then
    Result := ExpandConstant('{param:ISO|}')
  else
    Result := IsoPage.Values[0];
end;

{ Best-effort locale preview before extraction: lists the disc's table of
  contents (extract-xiso -l is a fast directory-only read, even on an 8 GB
  image) and looks for "<locale>_Common.cpk" entries. Purely informational -
  the config actually written after install is re-derived from the real
  extracted files. }
function PreviewDiscLocale(ExtractXisoExe, IsoPath: string; var LangId, CountryId: Integer; var LocaleName: string): Boolean;
var
  Names: TArrayOfString;
  ResultCode, i, P, Count: Integer;
  Lines: TArrayOfString;
  TmpFile: string;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}') + '\xiso_listing.txt';
  if FileExists(TmpFile) then DeleteFile(TmpFile);
  if not Exec(ExpandConstant('{cmd}'), '/C ""' + ExtractXisoExe + '" -l "' + IsoPath + '" > "' + TmpFile + '" 2>&1"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then Exit;
  if not FileExists(TmpFile) then Exit;
  if not LoadStringsFromFile(TmpFile, Lines) then Exit;

  SetArrayLength(Names, 0);
  Count := 0;
  for i := 0 to GetArrayLength(Lines) - 1 do
  begin
    P := Pos('_Common.cpk', Lines[i]);
    if P > 4 then
    begin
      SetArrayLength(Names, Count + 1);
      Names[Count] := Copy(Lines[i], P - 4, 15);
      Count := Count + 1;
    end;
  end;

  Result := DetectLocaleFromNames(Names, LangId, CountryId, LocaleName);
end;

function GetFileSizeInt64(FileName: string): Int64;
var
  FindRec: TFindRec;
  Hi, Lo: Int64;
begin
  Result := 0;
  if FindFirst(FileName, FindRec) then
  begin
    Hi := FindRec.SizeHigh;
    Lo := FindRec.SizeLow;
    if Lo < 0 then Lo := Lo + $100000000;
    Result := (Hi shl 32) + Lo;
    FindClose(FindRec);
  end;
end;

procedure IsoEditChange(Sender: TObject);
var
  LocaleName: string;
  SizeGb: string;
  IsoPath: string;
  GbVal: Extended;
  DetectedLangId, DetectedCountryId: Integer;
begin
  IsoPath := IsoPage.Values[0];
  if not FileExists(IsoPath) then
  begin
    IsoInfoLabel.Caption := '';
    Exit;
  end;
  GbVal := GetFileSizeInt64(IsoPath);
  GbVal := GbVal / 1073741824;
  SizeGb := Format('%.2f', [GbVal]);
  IsoInfoLabel.Caption := Format(CustomMessage('IsoChecking'), [SizeGb]);
  { Purely informational now (see GetLangIdCountryForActiveLanguage) - the
    installer's own language, chosen before this page even exists, is what
    actually determines the game's user_language/user_country. }
  if PreviewDiscLocale(ExpandConstant('{tmp}') + '\extract-xiso.exe', IsoPath, DetectedLangId, DetectedCountryId, LocaleName) then
    IsoInfoLabel.Caption := Format(CustomMessage('IsoDetected'), [SizeGb, GetLangDisplayName(DetectedLangId)])
  else
    IsoInfoLabel.Caption := Format(CustomMessage('IsoDefault'), [SizeGb]);
end;

function GetDirSizeBytes(Dir: string): Int64;
var
  FindRec: TFindRec;
  Total: Int64;
begin
  Total := 0;
  if FindFirst(Dir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
            Total := Total + GetDirSizeBytes(Dir + '\' + FindRec.Name)
          else
            Total := Total + GetFileSizeInt64(Dir + '\' + FindRec.Name);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  Result := Total;
end;

function FindFileRecursive(Dir, TargetName: string; var FoundPath: string): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(Dir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          if FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          begin
            if FindFileRecursive(Dir + '\' + FindRec.Name, TargetName, FoundPath) then
            begin
              Result := True;
              Exit;
            end;
          end
          else if CompareText(FindRec.Name, TargetName) = 0 then
          begin
            FoundPath := Dir + '\' + FindRec.Name;
            Result := True;
            Exit;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

{ Runs extract-xiso asynchronously and polls the destination folder's
  growing size against the (approximate - the source ISO's own size, close
  enough for a progress bar) total, updating the shared Installing page's
  progress gauge every ~250ms without blocking the UI. }
function RunExtractXisoAsync(ExePath, IsoPath, DestDir: string; TotalBytes: Int64): Boolean;
var
  StartupInfo: TIsoStartupInfo;
  ProcessInfo: TIsoProcessInformation;
  ExitCode: Longint;
  CmdLine: string;
  CurBytes: Int64;
  Pct: Integer;
  CurGb, TotalGb: Extended;
begin
  Result := False;
  StartupInfo.cb := SizeOf(StartupInfo);
  StartupInfo.dwFlags := IsoStartfUseShowWindow;
  StartupInfo.wShowWindow := IsoSwHide;

  CmdLine := '"' + ExePath + '" -x -d "' + DestDir + '" "' + IsoPath + '"';

  if not CreateProcessW(ExePath, CmdLine, 0, 0, False, IsoCreateNoWindow, 0, DestDir, StartupInfo, ProcessInfo) then
  begin
    GExtractError := 'Could not start extract-xiso.exe (Win32 error ' + IntToStr(DLLGetLastError) + ').';
    Exit;
  end;

  try
    while WaitForSingleObject(ProcessInfo.hProcess, 250) = IsoWaitTimeout do
    begin
      CurBytes := GetDirSizeBytes(DestDir);
      if TotalBytes > 0 then
      begin
        Pct := 5 + Round((CurBytes / TotalBytes) * 55);
        if Pct > 60 then Pct := 60;
      end else
        Pct := 30;
      WizardForm.ProgressGauge.Position := Pct;
      CurGb := CurBytes; CurGb := CurGb / 1073741824;
      TotalGb := TotalBytes; TotalGb := TotalGb / 1073741824;
      WizardForm.StatusLabel.Caption := Format(CustomMessage('StatusExtractingProgress'), [
        Format('%.1f', [CurGb]), Format('%.1f', [TotalGb])]);
    end;
    GetExitCodeProcess(ProcessInfo.hProcess, ExitCode);
    Result := (ExitCode = 0);
    if not Result then
      GExtractError := 'extract-xiso failed (exit code ' + IntToStr(ExitCode) + '). Make sure the file is a valid Xbox 360 Diablo III disc image.';
  finally
    CloseHandle(ProcessInfo.hProcess);
    CloseHandle(ProcessInfo.hThread);
  end;
end;

procedure WriteGameConfig(InstallDir, GameRoot: string; LangId, CountryId: Integer);
var
  Content, GameRootSlashed: string;
begin
  GameRootSlashed := GameRoot;
  StringChangeEx(GameRootSlashed, '\', '/', False);
  Content :=
    '# Souls of the Reaper - runtime config' + #13#10 +
    '# Generated by the installer.' + #13#10 +
    'game_data_root = "' + GameRootSlashed + '"' + #13#10 +
    'render_target_path_d3d12 = "rtv"' + #13#10 +
    'rtv_color_depth_ownership_mode = 8' + #13#10 +
    'execute_unclipped_draw_vs_on_cpu = true' + #13#10 +
    'd3_frame_limit = 120' + #13#10 +
    'vsync = false' + #13#10 +
    'draw_resolution_scale_x = 1' + #13#10 +
    'draw_resolution_scale_y = 1' + #13#10 +
    'present_effect = "fsr"' + #13#10 +
    'fullscreen = true' + #13#10 +
    'mnk_mode = true' + #13#10 +
    'mnk_mouse = false' + #13#10 +
    'mnk_cursor_visible = true' + #13#10 +
    'user_language = ' + IntToStr(LangId) + #13#10 +
    'user_country = ' + IntToStr(CountryId) + #13#10;
  SaveStringToFile(InstallDir + '\diablo3.toml', Content, False);
end;

{ Orchestrates the actual game-data install: extract the ISO, relocate the
  CPKs + Default.xex into the install dir's "game" folder, detect the
  disc's language, write diablo3.toml. Runs on the standard Installing page,
  reusing its progress
  gauge/status label after Inno's own (quick, small) [Files] copy finishes. }
function ExtractGameData(): Boolean;
var
  InstallDir, IsoFile, TempDir, ExtractExe, GameOut, CpkOut, ExtractedRoot, XexPath: string;
  TotalBytes: Int64;
  LangId, CountryId: Integer;
begin
  Result := False;
  InstallDir := ExpandConstant('{app}');
  IsoFile := GetIsoPath();

  if not FileExists(IsoFile) then
  begin
    GExtractError := 'Disc image not found: ' + IsoFile;
    Exit;
  end;

  ExtractExe := InstallDir + '\tools\extract-xiso.exe';
  TempDir := InstallDir + '\_setup_temp';
  if DirExists(TempDir) then DelTree(TempDir, True, True, True);
  ForceDirectories(TempDir);

  TotalBytes := GetFileSizeInt64(IsoFile);

  WizardForm.StatusLabel.Caption := CustomMessage('StatusExtracting');
  WizardForm.ProgressGauge.Style := npbstNormal;
  WizardForm.ProgressGauge.Min := 0;
  WizardForm.ProgressGauge.Max := 100;
  WizardForm.ProgressGauge.Position := 5;
  WizardForm.CancelButton.Enabled := False;

  if not RunExtractXisoAsync(ExtractExe, IsoFile, TempDir, TotalBytes) then
  begin
    WizardForm.CancelButton.Enabled := True;
    DelTree(TempDir, True, True, True);
    Exit;
  end;
  WizardForm.CancelButton.Enabled := True;

  WizardForm.StatusLabel.Caption := CustomMessage('StatusLocating');
  WizardForm.ProgressGauge.Position := 62;

  if not FindFileRecursive(TempDir, 'Common.cpk', ExtractedRoot) then
  begin
    GExtractError := 'Common.cpk was not found in the extracted disc. This does not look like the Xbox 360 version of Diablo III (Ultimate Evil Edition).';
    DelTree(TempDir, True, True, True);
    Exit;
  end;
  ExtractedRoot := ExtractFileDir(ExtractedRoot);

  { Default.xex sits alongside the CPKs on disc; move it out first so the
    whole-folder move below doesn't need to special-case it either way. }
  if FindFileRecursive(TempDir, 'Default.xex', XexPath) then
  begin
    GameOut := InstallDir + '\game';
    ForceDirectories(GameOut);
    MoveFileW(XexPath, GameOut + '\Default.xex');
  end;

  GameOut := InstallDir + '\game';
  CpkOut := GameOut + '\CPKs';
  ForceDirectories(GameOut);
  if DirExists(CpkOut) then DelTree(CpkOut, True, True, True);

  WizardForm.StatusLabel.Caption := CustomMessage('StatusInstallingData');
  WizardForm.ProgressGauge.Position := 80;

  if not MoveFileW(ExtractedRoot, CpkOut) then
  begin
    GExtractError := 'Could not move extracted game data into place (Win32 error ' + IntToStr(DLLGetLastError) + ').';
    DelTree(TempDir, True, True, True);
    Exit;
  end;

  DelTree(TempDir, True, True, True);

  WizardForm.StatusLabel.Caption := CustomMessage('StatusApplyingLang');
  WizardForm.ProgressGauge.Position := 92;

  { The game's language is the installer's own wizard language (ActiveLanguage
    - chosen via Inno's native startup language dialog / the standard
    /LANG=<name> silent switch), not auto-detected from the extracted CPKs. }
  GetLangIdCountryForActiveLanguage(LangId, CountryId);

  WizardForm.StatusLabel.Caption := CustomMessage('StatusWritingConfig');
  WizardForm.ProgressGauge.Position := 97;

  WriteGameConfig(InstallDir, GameOut, LangId, CountryId);

  WizardForm.ProgressGauge.Position := 100;
  WizardForm.StatusLabel.Caption := CustomMessage('StatusComplete');

  Result := True;
end;

procedure InitializeWizard();
begin
  InitLocaleTable;
  ExtractTemporaryFile('extract-xiso.exe');

  IsoPage := CreateInputFilePage(wpSelectDir, CustomMessage('IsoPageCaption'),
    CustomMessage('IsoPageDescription'), CustomMessage('IsoPageSubCaption'));
  IsoPage.Add('', 'Xbox 360 disc image|*.iso;*.xiso|All files|*.*', '.iso');
  IsoPage.Edits[0].OnChange := @IsoEditChange;

  IsoInfoLabel := TNewStaticText.Create(IsoPage);
  IsoInfoLabel.Parent := IsoPage.Surface;
  IsoInfoLabel.Top := IsoPage.Edits[0].Top + IsoPage.Edits[0].Height + ScaleY(16);
  IsoInfoLabel.Width := IsoPage.SurfaceWidth;
  IsoInfoLabel.AutoSize := False;
  IsoInfoLabel.Height := ScaleY(40);
  IsoInfoLabel.WordWrap := True;
  IsoInfoLabel.Caption := '';

  if ExpandConstant('{param:ISO|}') <> '' then
    IsoPage.Values[0] := ExpandConstant('{param:ISO}');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WizardSilent and (ExpandConstant('{param:ISO|}') = '') then
    Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = IsoPage.ID then
  begin
    if not FileExists(IsoPage.Values[0]) then
    begin
      MsgBox('Please select a valid Diablo III disc image (.iso) before continuing.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ ExtractGameData() failing after ssPostInstall leaves the [Files]/[Icons]/
  registry entries already in place (Abort alone does not roll those back) -
  without this, a failed install would still show up as a normal, apparently
  successful "Souls of the Reaper" entry in Programs & Features. Cleans up
  our own extra folders, then reuses the just-installed uninstaller (already
  registered and know how to remove everything Inno itself placed) to undo
  the rest before aborting. }
procedure CleanupFailedInstall();
var
  ResultCode: Integer;
  InstallDir: string;
begin
  InstallDir := ExpandConstant('{app}');
  if DirExists(InstallDir + '\game') then DelTree(InstallDir + '\game', True, True, True);
  if DirExists(InstallDir + '\_setup_temp') then DelTree(InstallDir + '\_setup_temp', True, True, True);
  DeleteFile(InstallDir + '\diablo3.toml');
  if FileExists(ExpandConstant('{uninstallexe}')) then
    Exec(ExpandConstant('{uninstallexe}'), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not ExtractGameData() then
    begin
      if not WizardSilent then
        MsgBox(CustomMessage('InstallFailedMsg') + #13#10#13#10 + GExtractError, mbCriticalError, MB_OK);
      CleanupFailedInstall();
      Abort;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  GameDir, StashDir: string;
  KeepData: Boolean;
begin
  if CurUninstallStep = usUninstall then
  begin
    GameDir := ExpandConstant('{app}') + '\game';
    if DirExists(GameDir) then
    begin
      if UninstallSilent then
        KeepData := (ExpandConstant('{param:KEEPDATA|}') <> '')
      else
        KeepData := (MsgBox('Keep the extracted game data (CPKs, ~7.5 GB) so you can reinstall quickly later without the disc?',
          mbConfirmation, MB_YESNO) = IDYES);
      if KeepData then
      begin
        StashDir := ExtractFileDir(ExpandConstant('{app}')) + '\{#MyAppName} Game Data';
        if DirExists(StashDir) then DelTree(StashDir, True, True, True);
        if MoveFileW(GameDir, StashDir) then
        begin
          if not UninstallSilent then
            MsgBox('Your game data was preserved at:' + #13#10 + StashDir, mbInformation, MB_OK);
        end else
        begin
          if not UninstallSilent then
            MsgBox('Could not preserve game data (Win32 error ' + IntToStr(DLLGetLastError) + '). It will be removed.', mbError, MB_OK);
        end;
      end else
        DelTree(GameDir, True, True, True);
    end;
    DeleteFile(ExpandConstant('{app}') + '\diablo3.toml');
    if DirExists(ExpandConstant('{app}') + '\_setup_temp') then
      DelTree(ExpandConstant('{app}') + '\_setup_temp', True, True, True);
  end;
end;
