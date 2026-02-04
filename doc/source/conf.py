from datetime import date

project = 'EO4EU Documentation'
copyright = f'{date.today().year}, EO4EU Team'
author = 'EO4EU Team'
release = '1.0.0'

extensions = [
    'sphinx_rtd_theme',
]

html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    # 'display_version': True,
}
html_static_path = ['_static']

rst_epilog = f'''
.. |project| replace:: {project}
'''

nitpicky = True
html_css_files = [
  './service-doc.css'
]