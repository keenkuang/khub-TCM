# khub shell 自动补全
_khub_complete() {
    local cur=${COMP_WORDS[COMP_CWORD]}
    local prev=${COMP_WORDS[COMP_CWORD-1]}
    local cmds="help serve login logout whoami user-list user-create user-role course-create course-list course-info lesson-add lesson-list enroll grade kg-infer kg-herbs kg-formulas kg-similarity report-create report-list report-run report-export workflow-create workflow-list workflow-run workflow-instances audit-search retention-clean sync-status sync-push sync-pull completion"
    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=($(compgen -W "$cmds" -- $cur))
    fi
}
complete -F _khub_complete khub
