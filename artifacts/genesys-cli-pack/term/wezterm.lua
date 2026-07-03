local wezterm = require 'wezterm'
return {
  font = wezterm.font_with_fallback({ 'JetBrainsMono Nerd Font', 'monospace' }),
  font_size = 12.0,
  use_fancy_tab_bar = true,
  hide_tab_bar_if_only_one_tab = true,
  default_prog = { '/usr/bin/zsh', '-l' },
}
