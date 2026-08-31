SELECT count(*)
FROM aka_title, cast_info, char_name, kind_type, movie_info_idx, title
WHERE char_name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info_idx.movie_id = title.id
  AND title.kind_id = kind_type.id;
