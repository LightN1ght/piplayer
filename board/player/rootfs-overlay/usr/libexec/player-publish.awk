BEGIN {
    FS = "|"
    # Avoid awk's default six-significant-digit formatting for long-running
    # media sequence numbers, which otherwise becomes invalid scientific notation.
    OFMT = "%.17g"; CONVFMT = "%.17g"
    nextseq = 0; lastgen = ""; cursor = -1; discontinuities = 0
}
FILENAME == statefile {
    if ($1 == "M") {
        nextseq = $2 + 0; lastgen = $3; cursor = $4 + 0; discontinuities = $5 + 0
    } else if ($1 == "E") {
        n++; seq[n]=$2+0; gen[n]=$3; priv[n]=$4+0; name[n]=$5
        dur[n]=$6+0; boundary[n]=$7+0; disc[n]=$8+0; retired[n]=$9+0
    }
    next
}
{
    if ($0 ~ /^#EXT-X-MEDIA-SEQUENCE:/) {
        x=$0; sub(/^#EXT-X-MEDIA-SEQUENCE:/, "", x)
        if (x !~ /^[0-9]+$/) invalid=1
        private_seq=x+0; have_seq=1
    } else if ($0 ~ /^#EXTINF:/) {
        x=$0; sub(/^#EXTINF:/, "", x); sub(/,.*/, "", x)
        if (x !~ /^[0-9]+([.][0-9]+)?$/ || x+0 <= 0 || x+0 > 6) invalid=1
        pending_duration=x+0; have_duration=1
    } else if ($0 !~ /^#/ && $0 != "") {
        if (!have_seq || !have_duration || $0 !~ /^[A-Za-z0-9_.-]+\.ts$/ || $0 ~ /^\./) invalid=1
        items++; newname[items]=$0; newdur[items]=pending_duration; newpriv[items]=private_seq
        private_seq++; have_duration=0
    }
}
END {
    if (invalid || !have_seq || have_duration || !items) exit 1
    if (lastgen != generation) {
        lastgen=generation; cursor=-1
    }
    for (i=1; i<=items; i++) {
        if (newpriv[i] <= cursor) continue
        marker=(nextseq > 0 && (cursor < 0 || newpriv[i] > cursor+1)) ? 1 : 0
        if (marker) discontinuities++
        n++; seq[n]=nextseq++; gen[n]=generation; priv[n]=newpriv[i]
        name[n]=newname[i]; dur[n]=newdur[i]; boundary[n]=marker
        disc[n]=discontinuities; retired[n]=-1; cursor=newpriv[i]
    }
    total=0
    for (i=1; i<=n; i++) if (retired[i] == -1) total+=dur[i]
    # Keep at least 20 seconds live; with maximum duration 6s this bounds the
    # advertised window below 26 seconds after the first trim.
    for (i=1; i<=n; i++) {
        if (retired[i] != -1) continue
        if (total-dur[i] < 20) break
        total-=dur[i]; retired[i]=now
    }
    first=0
    for (i=1; i<=n; i++) if (retired[i] == -1) { first=i; break }
    print "M|" nextseq "|" lastgen "|" cursor "|" discontinuities > stateout
    for (i=1; i<=n; i++) {
        if (retired[i] != -1 && now-retired[i] >= 36) {
            print "D|" seq[i] "|" gen[i] "|" priv[i] "|" name[i] "|" dur[i] "|" boundary[i] "|" disc[i] "|" retired[i] >> stateout
        } else {
            print "E|" seq[i] "|" gen[i] "|" priv[i] "|" name[i] "|" dur[i] "|" boundary[i] "|" disc[i] "|" retired[i] >> stateout
        }
    }
    close(stateout)
    if (!first) exit
    print "#EXTM3U" > listout
    print "#EXT-X-VERSION:3" >> listout
    print "#EXT-X-TARGETDURATION:6" >> listout
    print "#EXT-X-MEDIA-SEQUENCE:" seq[first] >> listout
    print "#EXT-X-DISCONTINUITY-SEQUENCE:" disc[first]-boundary[first] >> listout
    for (i=1; i<=n; i++) {
        if (retired[i] != -1) continue
        if (boundary[i]) print "#EXT-X-DISCONTINUITY" >> listout
        printf "#EXTINF:%.6f,\n/hls/%s/%s\n", dur[i], gen[i], name[i] >> listout
    }
    close(listout)
}
