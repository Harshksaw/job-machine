%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Medium Length Professional CV - RESUME CLASS FILE
%
% This template has been downloaded from:
% http://www.LaTeXTemplates.com
%
% This class file defines the structure and design of the template. 
%
% Original header:
% Copyright (C) 2010 by Trey Hunner
%
% Copying and distribution of this file, with or without modification,
% are permitted in any medium without royalty provided the copyright
% notice and this notice are preserved. This file is offered as-is,
% without any warranty.
%
% Created by Trey Hunner and modified by www.LaTeXTemplates.com
%
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\ProvidesClass{resume}[2010/07/10 v0.9 Resume class]

\LoadClass[10pt,letterpaper]{article} % Font size and paper type

\usepackage[parfill]{parskip} % Remove paragraph indentation
\usepackage{array} % Required for boldface (\bf and \bfseries) tabular columns
\usepackage{ifthen} % Required for ifthenelse statements
% Tightened margins so a full one-page resume's worth of real content (all
% jobs/bullets, both projects, all achievements) fits on a single page --
% the article class's ~1in default margins waste too much space for that
% density.
\usepackage[top=0.3in, bottom=0.3in, left=0.6in, right=0.6in]{geometry}

% Body text at 9pt/10.5pt (rather than the standard 10pt \normalsize) using
% the kernel's own \@setfontsize -- plain \LoadClass[9pt]{article} isn't
% valid (article only supports 10/11/12pt), and switching to the extsizes
% `extarticle` class for a real 9pt option caused pdflatex to hang
% indefinitely (some interaction with this file's \document redefinition
% below), so this redefines \normalsize in place instead. Needed, together
% with the tighter margins/list spacing throughout this file, to fit the
% full one-page resume's worth of real content on a single page.
\renewcommand{\normalsize}{\@setfontsize\normalsize{9pt}{10.5pt}}
\normalsize

\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    filecolor=magenta,      
    urlcolor=blue,
}

\pagestyle{empty} % Suppress page numbers

%----------------------------------------------------------------------------------------
%	HEADINGS COMMANDS: Commands for printing name and address
%----------------------------------------------------------------------------------------

\def \name#1{\def\@name{#1}} % Defines the \name command to set name
\def \@name {} % Sets \@name to empty by default

\def \addressSep {$|$} % Set default address separator to a diamond

% One, two or three address lines can be specified 
\let \@addressone \relax
\let \@addresstwo \relax
\let \@addressthree \relax

% \address command can be used to set the first, second, and third address (last 2 optional)
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

% \printaddress is used to style an address line (given as input)
\def \printaddress #1{
  \begingroup
    \def \\ {\addressSep\ }
    \centerline{#1}
  \endgroup
  \par
  \addressskip
}

% \printname is used to print the name as a page header
\def \printname {
  \begingroup
    \hfil{\MakeUppercase{\namesize\bf \@name}}\hfil
    \nameskip\break
  \endgroup
}

%----------------------------------------------------------------------------------------
%	PRINT THE HEADING LINES
%----------------------------------------------------------------------------------------

\let\ori@document=\document
\renewcommand{\document}{
  \ori@document  % Begin document
  \printname % Print the name specified with \name
  \@ifundefined{@addressone}{}{ % Print the first address if specified
    \printaddress{\@addressone}}
  \@ifundefined{@addresstwo}{}{ % Print the second address if specified
    \printaddress{\@addresstwo}}
     \@ifundefined{@addressthree}{}{ % Print the third address if specified
    \printaddress{\@addressthree}}
}

%----------------------------------------------------------------------------------------
%	SECTION FORMATTING
%----------------------------------------------------------------------------------------

% Defines the rSection environment for the large sections within the CV
\newenvironment{rSection}[1]{ % 1 input argument - section name
  \sectionskip
  \MakeUppercase{{\bf #1}} % Section title
  \sectionlineskip
  \hrule % Horizontal line
  \begin{list}{}{ % List for each individual item in the section
    \setlength{\leftmargin}{0em} % Margin within the section
    \setlength{\itemsep}{0pt} % Compress spacing between items (e.g. projects, achievements)
    \setlength{\parsep}{0pt}
    \setlength{\topsep}{0pt}
  }
  \item[]
}{
  \end{list}
}

%----------------------------------------------------------------------------------------
%	WORK EXPERIENCE FORMATTING
%----------------------------------------------------------------------------------------

\newenvironment{rSubsection}[4]{ % 4 input arguments - company name, year(s) employed, job title and location
 {\bf #1} \hfill {#2} % Bold company name and date on the right
 \ifthenelse{\equal{#3}{}}{}{ % If the third argument is not specified, don't print the job title and location line
  \\
  {\em #3} \hfill {\em #4} % Italic job title and location
  }
  \begin{list}{$\cdot$}{\leftmargin=1em} % \cdot used for bullets, no indentation
   % NOTE: \itemsep/\parsep/\topsep only affect spacing BETWEEN items (and
   % around the whole list) -- do not add a raw \vspace here as well. An
   % earlier version stacked a \vspace before this list on top of another
   % \vspace at the list's start, and the two negative skips compounded to
   % pull the first bullet up so far it visually overlapped the job
   % title/location line above it. Keep this purely length-based.
   \itemsep -0.3em \parsep 0pt \topsep 0.15em % Compress items in list together for aesthetics
  }{
  \end{list}
}

% The below commands define the whitespace after certain things in the document - they can be \smallskip, \medskip or \bigskip
\def\namesize{\Large} % Size of the name at the top of the document
\def\addressskip{\vspace{0.02em}} % The space between the two address (or phone/email) lines
\def\sectionlineskip{\vspace{0.02em}} % The space above the horizontal line for each section
\def\nameskip{\vspace{0.05em}} % The space after your name at the top
\def\sectionskip{\vspace{0.15em}} % The space after the heading section
