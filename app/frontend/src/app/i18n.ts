import { useProfile } from "./ProfileContext";

const tr: Record<string, string> = {
  "Add Profile": "Profil Ekle", "Cancel": "Vazgeç",
  "New profiles are viewers.": "Yeni profiller izleyici olur.",
  "Defaults to the profile name": "Varsayılan olarak profil adını kullanır",
  "Choose a profile to keep progress and preferences separate.": "İlerleme ve tercihleri ayrı tutmak için bir profil seçin.",
  "Who's watching?": "Kim izliyor?", "New profile": "Yeni profil", "Profile name": "Profil adı",
  "Create": "Oluştur", "Creating…": "Oluşturuluyor…", "Loading…": "Yükleniyor…",
  "Try again": "Tekrar dene", "Save": "Kaydet", "Saved": "Kaydedildi", "Remove": "Kaldır",
  "Browse": "Keşfet", "Admin": "Yönetim", "Profile": "Profil", "Library": "Kitaplık",
  "Owner login": "Yönetici girişi", "Password": "Parola", "Sign in": "Giriş yap", "Sign out": "Çıkış yap",
  "Owner password is not configured. Run the local owner setup command.": "Yönetici parolası belirlenmemiş. Yerel owner kurulum komutunu çalıştırın.",
  "Owner authentication required": "Yönetici doğrulaması gerekli", "Invalid owner credentials": "Yönetici parolası yanlış",
  "Welcome to Orbis": "Orbis'e hoş geldiniz", "Interface language": "Arayüz dili", "Continue": "Devam et",
  "Create installation owner": "Kurulum sahibini oluştur", "Use at least 12 characters": "En az 12 karakter kullanın",
  "Profile preferences": "Profil tercihleri", "Avatar seed": "Avatar anahtarı", "New avatar": "Yeni avatar",
  "Audio language": "Ses dili", "Subtitle language": "Altyazı dili", "Provider default": "Sağlayıcı varsayılanı",
  "Subtitles enabled": "Altyazılar açık", "Autoplay next episode": "Sonraki bölümü otomatik oynat", "Mute trailers": "Fragmanları sessiz oynat",
  "Choose up to five movies or series": "En fazla beş film veya dizi seçin", "Search": "Ara", "Selected": "Seçildi",
  "My List": "Listem", "History": "Geçmiş", "Continue Watching": "İzlemeye Devam Et",
  "All": "Tümü", "Movies": "Filmler", "Series": "Diziler", "Nothing here yet": "Henüz bir şey yok",
  "Resume": "Devam et", "Start Over": "Baştan başlat", "Play Again": "Tekrar izle", "Play": "Oynat", "Play again": "Tekrar izle",
  "Next episode": "Sonraki bölüm", "Remove from Continue Watching": "İzlemeye Devam Et'ten kaldır",
  "Add to My List": "Listeme ekle", "Remove from My List": "Listemden kaldır", "Not Interested": "İlgilenmiyorum", "Clear feedback": "Geri bildirimi temizle",
  "Meaningful viewing": "Anlamlı izleme", "Brief start": "Kısa açılış", "Completions": "Tamamlamalar", "Rewatches": "Tekrar izlemeler",
  "Trending today": "Bugün popüler", "Season": "Sezon", "Episodes": "Bölümler", "Back": "Geri",
  "Request failed": "İstek başarısız", "Owner": "Yönetici", "Viewer": "İzleyici",
};

export function translate(locale: string, value: string) { return locale === "tr-TR" ? tr[value] ?? value : value; }
export function useText() {
  const { profile, setup } = useProfile();
  return (value: string) => translate(profile?.locale ?? setup?.locale ?? "en-US", value);
}
