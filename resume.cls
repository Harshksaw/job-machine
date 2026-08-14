%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Medium Length Professional CV - RESUME CLASS FILE
% http://www.LaTeXTemplates.com
% Copyright (C) 2010 by Trey Hunner
% Created by Trey Hunner and modified by www.LaTeXTemplates.com
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\ProvidesClass{resume}[2010/07/10 v0.9 Resume class]

\LoadClass[11pt,letterpaper]{article}

\usepackage[parfill]{parskip}
\usepackage{array}
\usepackage{ifthen}
\usepackage{enumitem}

% ATS FIX: default LaTeX bullet is a Type 3 bitmap that extracts as U+0088.
% This forces a Type 1 glyph that extracts as a real U+2022 bullet.
\renewcommand{\labelitemi}{$\bullet$}

% One-line job header: Title | Company, Location .......... Dates
\newcommand{\job}[5]{%
  \vspace{3pt}%
  \noindent\textbf{#1} \textbar{} \textbf{\href{#3}{#2}}, #4 \hfill #5\par
  \vspace{-8pt}%
}

% Tight bullet list for job/project entries
\newenvironment{jobitems}
  {\begin{itemize}[leftmargin=1.1em,itemsep=0pt,topsep=3pt,parsep=0pt,partopsep=0pt,after=\vspace{2pt}]}
  {\end{itemize}}

% One-line education header: Degree | School, Location .......... Dates
\newcommand{\edu}[4]{%
  \vspace{2pt}%
  \noindent\textbf{#1} \textbar{} \textbf{#2}, #3 \hfill #4\par
  \vspace{-2pt}%
}

\newcommand{\coursework}[1]{%
  \noindent\textit{Relevant coursework:} #1\par\vspace{2pt}%
}

\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    filecolor=magenta,
    urlcolor=blue,
}

\pagestyle{empty}

%----------------------------------------------------------------------------------------
% HEADINGS COMMANDS
%----------------------------------------------------------------------------------------

\def \name#1{\def\@name{#1}}
\def \@name {}

\def \addressSep {$|$}

\let \@addressone \relax
\let \@addresstwo \relax
\let \@addressthree \relax

\def \address #1{
  \@ifundefined{@addressone}{
    \def \@addressone {#1}
  }{
  \@ifundefined{@addresstwo}{
  \def \@addresstwo {#1}
  }{
     \def \@addressthree {#1}
  }}
}

\def \printaddress #1{
  \begingroup
    \def \\ {\addressSep\ }
    \centerline{#1}
  \endgroup
  \par
  \addressskip
}

\def \printname {
  \begingroup
    \hfil{\MakeUppercase{\namesize\bf \@name}}\hfil
    \nameskip\break
  \endgroup
}

%----------------------------------------------------------------------------------------
% PRINT THE HEADING LINES
%----------------------------------------------------------------------------------------

\let\ori@document=\document
\renewcommand{\document}{
  \ori@document
  \printname
  \@ifundefined{@addressone}{}{
    \printaddress{\@addressone}}
  \@ifundefined{@addresstwo}{}{
    \printaddress{\@addresstwo}}
  \@ifundefined{@addressthree}{}{
    \printaddress{\@addressthree}}
}

%----------------------------------------------------------------------------------------
% SECTION FORMATTING
%----------------------------------------------------------------------------------------

\newenvironment{rSection}[1]{
  \sectionskip
  \MakeUppercase{{\bf #1}}
  \sectionlineskip
  \hrule
  \begin{list}{}{
    \setlength{\leftmargin}{0em}
  }
  \item[]
}{
  \end{list}
}

%----------------------------------------------------------------------------------------
% WORK EXPERIENCE FORMATTING (legacy - unused)
%----------------------------------------------------------------------------------------

\newenvironment{rSubsection}[4]{
 {\bf #1} \hfill {#2}
 \ifthenelse{\equal{#3}{}}{}{
  \\
  {\em #3} \hfill {\em #4}
  }\smallskip
  \begin{list}{$\cdot$}{\leftmargin=0em}
   \itemsep -0.5em \vspace{-0.5em}
  }{
  \end{list}
  \vspace{0.5em}
}

\def\namesize{\LARGE}
\def\addressskip{\smallskip}
\def\sectionlineskip{\medskip}
\def\nameskip{\medskip}
\def\sectionskip{\medskip}
