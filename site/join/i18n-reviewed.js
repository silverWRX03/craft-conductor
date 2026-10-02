"use strict";
// Human-reviewed corrections layered over the machine-made invite-page translations in i18n.js.
// Keeping these separate makes future machine regeneration safe without losing reviewed wording.
const SITE_I18N_REVIEWED = {
  es: {
    "Craft Conductor finds your invite by itself and sets up Minecraft: pick your launcher and press the button.": "Craft Conductor encuentra tu invitación automáticamente y prepara Minecraft: elige tu launcher y pulsa el botón.",
  },
  pt: {
    "Craft Conductor finds your invite by itself and sets up Minecraft: pick your launcher and press the button.": "O Craft Conductor encontra seu convite automaticamente e configura o Minecraft: escolha seu launcher e aperte o botão.",
    "Nothing happened? Craft Conductor isn't set up to open links on this computer yet (Macs, or Craft Conductor never run): download it above and open it; the invite is already copied for it.": "Nada aconteceu? O Craft Conductor ainda não está configurado para abrir links neste computador (em Macs, ou se o Craft Conductor nunca foi executado): baixe-o acima e abra-o; o convite já está copiado.",
  },
  fr: {
    "Craft Conductor finds your invite by itself and sets up Minecraft: pick your launcher and press the button.": "Craft Conductor trouve automatiquement votre invitation et configure Minecraft : choisissez votre lanceur et appuyez sur le bouton.",
    "Nothing happened? Craft Conductor isn't set up to open links on this computer yet (Macs, or Craft Conductor never run): download it above and open it; the invite is already copied for it.": "Rien ne se passe ? Craft Conductor n’est pas encore configuré pour ouvrir les liens sur cet ordinateur (sur Mac, ou s’il n’a encore jamais été lancé) : téléchargez-le ci-dessus et ouvrez-le ; l’invitation est déjà copiée.",
  },
  de: {
    "Run": "Ausführen",
    "The link you opened didn't bring its invite with it (some apps cut links short).": "Der geöffnete Link enthielt die Einladung nicht (manche Apps kürzen Links).",
    "with this invite code, or paste it into Craft Conductor:": "mit diesem Einladungscode, oder füge ihn in Craft Conductor ein:",
  },
  ar: {
    "Craft Conductor checks it's really your friend's server before connecting, and downloads mods only from Modrinth and CurseForge.": "يتحقق Craft Conductor من أنه خادم صديقك فعلًا قبل الاتصال، ولا ينزّل التعديلات إلا من Modrinth وCurseForge.",
    "Craft Conductor sets up your Minecraft for this server: the right version and mods, in a folder of its own. Your other worlds aren't touched, and you sign in with your own Minecraft account as usual.": "يُعدّ Craft Conductor لعبة Minecraft لديك لهذا الخادم: الإصدار والتعديلات الصحيحة في مجلد خاص بها. لا تُمَس عوالمك الأخرى، وتسجّل الدخول بحساب Minecraft الخاص بك كالمعتاد.",
  },
  ko: {
    "Already have Craft Conductor?": "이미 Craft Conductor가 있나요?",
    "Craft Conductor checks it's really your friend's server before connecting, and downloads mods only from Modrinth and CurseForge.": "Craft Conductor는 연결 전에 정말 친구의 서버인지 확인하며, 모드는 Modrinth와 CurseForge에서만 다운로드합니다.",
    "Craft Conductor finds your invite by itself and sets up Minecraft: pick your launcher and press the button.": "Craft Conductor가 초대를 자동으로 찾아 Minecraft를 설정합니다. 런처를 고르고 버튼을 누르세요.",
    "Craft Conductor sets up your Minecraft for this server: the right version and mods, in a folder of its own. Your other worlds aren't touched, and you sign in with your own Minecraft account as usual.": "Craft Conductor가 이 서버에 맞게 Minecraft를 설정합니다. 올바른 버전과 모드를 별도 폴더에 준비하며, 다른 월드는 건드리지 않고 평소처럼 본인 Minecraft 계정으로 로그인합니다.",
    "If Windows says it \"protected your PC\", choose More info → Run anyway: Craft Conductor is free and isn't code-signed.": "Windows에서 ‘PC를 보호했습니다’라고 하면 추가 정보 → 실행을 선택하세요. Craft Conductor는 무료이며 코드 서명이 없습니다.",
    "If your browser asks, choose Open. Craft Conductor brings back its page even if you closed that tab.": "브라우저가 물으면 열기를 선택하세요. 탭을 닫았어도 Craft Conductor가 페이지를 다시 엽니다.",
    "Invite copied: open Craft Conductor": "초대가 복사되었습니다: Craft Conductor를 여세요",
    "Nothing happened? Craft Conductor isn't set up to open links on this computer yet (Macs, or Craft Conductor never run): download it above and open it; the invite is already copied for it.": "아무 일도 없나요? 이 컴퓨터의 Craft Conductor가 아직 링크를 열도록 설정되지 않았습니다(Mac이거나 Craft Conductor를 실행한 적이 없는 경우). 위에서 다운로드해 여세요. 초대는 이미 복사되어 있습니다.",
    "Opening Craft Conductor…": "Craft Conductor를 여는 중…",
    "Run": "실행",
    "When Craft Conductor asks for your invite, paste this:": "Craft Conductor가 초대를 요청하면 이것을 붙여 넣으세요:",
  },
};

for (const [code, fixes] of Object.entries(SITE_I18N_REVIEWED)) {
  if (SITE_I18N[code]) Object.assign(SITE_I18N[code], fixes);
}
