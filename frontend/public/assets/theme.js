// Set the native color scheme and workspace palette before the first paint.
{
  let theme
  try {
    theme = localStorage.getItem('echo.theme.v1')
  } catch {
    // The browser can deny storage access. Use its color preference then.
  }
  document.documentElement.dataset.theme =
    theme === 'light' || theme === 'dark'
      ? theme
      : matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
}
