SELECT count(*)
FROM aka_name, cast_info, char_name, info_type, keyword, movie_keyword, name, person_info, title
WHERE char_name.name_pcode_nf = 'H5241'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
