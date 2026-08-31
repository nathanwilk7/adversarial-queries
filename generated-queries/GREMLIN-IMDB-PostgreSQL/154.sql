SELECT count(*)
FROM aka_title, cast_info, char_name, info_type, keyword, kind_type, link_type, movie_info, movie_keyword, movie_link, name, title
WHERE char_name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
