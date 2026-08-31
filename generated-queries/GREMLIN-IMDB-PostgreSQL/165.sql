SELECT count(*)
FROM aka_title, cast_info, kind_type, name, title
WHERE kind_type.kind = 'movie'
  AND name.name_pcode_nf = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND title.kind_id = kind_type.id;
